#Requires -Version 5.1
<#
.SYNOPSIS
Copies owned external inputs into the ignored local data directory.
.DESCRIPTION
Sources are retained. Every copied or existing file is verified with SHA256.
Conflicting destinations, reparse points and source/destination overlap fail.
A flushed JSONL journal preserves progress even if the process is terminated;
the JSON manifest is finalized on success, failure or a normal interruption.
.EXAMPLE
.\Tools\import_local_data.ps1 -GameSource D:\Downloads\vg -ResearchSource "$env:TEMP\vg_max"
#>
[CmdletBinding()]
param(
    [string]$GameSource,
    [string]$ResearchSource,
    [string]$StackSource,
    [string]$VolleySource,
    [string]$SpawnSource,
    [string]$LocalRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if ([string]::IsNullOrWhiteSpace($LocalRoot)) {
    $LocalRoot = Join-Path $projectRoot 'Local'
}
$gitIgnoreValidated = $false

function Get-FullPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -ne [IO.Path]::GetPathRoot($full)) {
        $full = $full.TrimEnd([char[]]'\/')
    }
    return $full
}

function Test-Within([string]$Path, [string]$Root) {
    return $Path.Equals($Root, [StringComparison]::OrdinalIgnoreCase) -or
        $Path.StartsWith($Root.TrimEnd([char[]]'\/') + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparsePath([string]$Path) {
    $cursor = $Path
    while ($cursor) {
        $attributes = 0
        try { $attributes = [IO.File]::GetAttributes($cursor) }
        catch [IO.FileNotFoundException] { }
        catch [IO.DirectoryNotFoundException] { }
        if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse points are not supported: $cursor"
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}

function Assert-Destination([string]$Path) {
    if (-not (Test-Within $Path $script:dataRoot)) {
        throw "Destination escapes LocalRoot: $Path"
    }
    Assert-NoReparsePath $Path
    if ((Test-Within $Path $script:projectRoot) -and -not $script:gitIgnoreValidated) {
        $relative = $script:dataRoot.Substring($script:projectRoot.Length).TrimStart([char[]]'\/') + '/'
        & git -C $script:projectRoot check-ignore --quiet -- $relative
        if ($LASTEXITCODE -ne 0) {
            throw "LocalRoot must be ignored by Git before import: $script:dataRoot"
        }
        $tracked = @(& git -C $script:projectRoot ls-files -- $relative)
        if ($LASTEXITCODE -ne 0 -or $tracked.Count -gt 0) {
            throw "LocalRoot must not contain tracked files: $script:dataRoot"
        }
        # An ignored directory hides all descendants. Validate once per run;
        # spawning Git for each asset would dominate large tree imports.
        $script:gitIgnoreValidated = $true
    }
}

function Get-InputFiles([string]$Root, [string]$Mode) {
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($Root)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        Assert-NoReparsePath $directory
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
            $selected = $Mode -eq 'tree' -or
                ($Mode -eq 'vgr' -and -not $item.PSIsContainer -and $item.Extension -ieq '.vgr') -or
                ($Mode -eq 'stack' -and $item.Name -in @(
                    'answers.json', 'platform_cert.pem', 'platform_key.pem',
                    'platform.cer', 'world_tape.bin'))
            if (-not $selected) { continue }
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Reparse points are not supported: $($item.FullName)"
            }
            if ($item.PSIsContainer) {
                if ($Mode -ne 'tree') { throw "Expected a file: $($item.FullName)" }
                $pending.Push($item.FullName)
            } else {
                $item
            }
        }
    }
}

$dataRoot = Get-FullPath $LocalRoot
Assert-Destination $dataRoot
$plans = @(
    @{ Source = $GameSource; Relative = 'vainglory'; Mode = 'tree' },
    @{ Source = $ResearchSource; Relative = 'research\vg_max'; Mode = 'tree' },
    @{ Source = $StackSource; Relative = 'runtime\halcyon_stack'; Mode = 'stack' },
    @{ Source = $VolleySource; Relative = 'research\runtime-corpus'; Mode = 'vgr' },
    @{ Source = $SpawnSource; Relative = 'research\runtime-corpus'; Mode = 'vgr' }
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Source) }

if (@($plans).Count -eq 0) { throw 'Specify at least one source directory.' }
# Validate all selected roots before creating or copying anything.
foreach ($plan in $plans) {
    $plan.Source = Get-FullPath $plan.Source
    Assert-NoReparsePath $plan.Source
    if (-not (Test-Path -LiteralPath $plan.Source -PathType Container)) {
        throw "Source directory does not exist: $($plan.Source)"
    }
    if ((Test-Within $plan.Source $dataRoot) -or (Test-Within $dataRoot $plan.Source)) {
        throw "Source and LocalRoot must not overlap: $($plan.Source) / $dataRoot"
    }
    Assert-Destination (Join-Path $dataRoot $plan.Relative)
}

$manifestDirectory = Join-Path $dataRoot 'manifests'
Assert-Destination $manifestDirectory
$null = New-Item -ItemType Directory -Path $manifestDirectory -Force
$runId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [Guid]::NewGuid().ToString('N')
$manifestPath = Join-Path $manifestDirectory "import-$runId.json"
$journalPath = Join-Path $manifestDirectory "import-$runId.jsonl"
Assert-Destination $manifestPath
Assert-Destination $journalPath
$utf8 = New-Object Text.UTF8Encoding($false)
$records = New-Object 'System.Collections.Generic.List[object]'
$manifest = [ordered]@{
    schema_version = 1
    started_utc = [DateTime]::UtcNow.ToString('o')
    completed_utc = $null
    status = 'RUNNING'
    local_root = $dataRoot
    journal = [IO.Path]::GetFileName($journalPath)
    sources = @($plans | ForEach-Object {
        [ordered]@{ source = $_.Source; destination = $_.Relative.Replace('\', '/'); mode = $_.Mode }
    })
    files = @()
    error = $null
}
[IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8), $utf8)
$journal = New-Object IO.StreamWriter($journalPath, $false, $utf8)
$journal.AutoFlush = $true
$currentRecord = $null
try {
    foreach ($plan in $plans) {
        $counts = @{ copied = 0; identical = 0; bytes = [long]0 }
        Get-InputFiles $plan.Source $plan.Mode | ForEach-Object {
            $source = $_.FullName
            $relative = $source.Substring($plan.Source.Length).TrimStart([char[]]'\/')
            $destination = Get-FullPath (Join-Path (Join-Path $dataRoot $plan.Relative) $relative)
            Assert-NoReparsePath $source
            Assert-Destination $destination
            $currentRecord = [ordered]@{
                source = $source
                destination = $destination.Substring($dataRoot.Length).TrimStart([char[]]'\/').Replace('\', '/')
                bytes = [long]$_.Length
                sha256 = $null
                status = 'HASHING'
                staging_file = $null
            }
            $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
            $currentRecord.sha256 = $sourceHash
            if (Test-Path -LiteralPath $destination) {
                if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
                    throw "Destination is not a file: $destination"
                }
                if ((Get-Item -LiteralPath $destination -Force).Length -ne $currentRecord.bytes -or
                    (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHash) {
                    throw "Refusing to overwrite different destination: $destination"
                }
                $currentRecord.status = 'IDENTICAL'
                $counts.identical++
            } else {
                $parent = Split-Path -Parent $destination
                Assert-Destination $parent
                $null = New-Item -ItemType Directory -Path $parent -Force
                $staging = Join-Path $parent ('.halcyon-import-' + [Guid]::NewGuid().ToString('N') + '.partial')
                Assert-Destination $staging
                $currentRecord.staging_file = $staging.Substring($dataRoot.Length).TrimStart([char[]]'\/').Replace('\', '/')
                $currentRecord.status = 'COPYING'
                $journal.WriteLine(($currentRecord | ConvertTo-Json -Depth 4 -Compress))
                Copy-Item -LiteralPath $source -Destination $staging
                $targetHash = (Get-FileHash -LiteralPath $staging -Algorithm SHA256).Hash.ToLowerInvariant()
                if ((Get-Item -LiteralPath $staging -Force).Length -ne $currentRecord.bytes -or $targetHash -ne $sourceHash) {
                    throw "SHA256 or size verification failed; staging file retained: $staging"
                }
                Assert-Destination $staging
                Assert-Destination $destination
                if (Test-Path -LiteralPath $destination) {
                    throw "Destination appeared during copy; staging file retained: $destination"
                }
                # Move only our verified staging file, never any original input.
                # Move-Item without -Force refuses a destination created concurrently.
                Move-Item -LiteralPath $staging -Destination $destination
                $currentRecord.staging_file = $null
                $currentRecord.status = 'COPIED'
                $counts.copied++
            }
            $counts.bytes += $currentRecord.bytes
            $journal.WriteLine(($currentRecord | ConvertTo-Json -Depth 4 -Compress))
            $records.Add($currentRecord)
            $currentRecord = $null
        }
        Write-Host ("{0}: copied={1}, identical={2}, verified_bytes={3}" -f
            $plan.Relative, $counts.copied, $counts.identical, $counts.bytes)
    }
    $manifest.status = 'COMPLETE'
} catch {
    $manifest.status = 'FAILED'
    $manifest.error = $_.Exception.Message
    throw
} finally {
    if ($manifest.status -eq 'RUNNING') { $manifest.status = 'INTERRUPTED' }
    if ($null -ne $currentRecord) {
        $currentRecord.status = $manifest.status
        $records.Add($currentRecord)
        $journal.WriteLine(($currentRecord | ConvertTo-Json -Depth 4 -Compress))
    }
    $journal.Dispose()
    $manifest.files = @($records.ToArray())
    $manifest.completed_utc = [DateTime]::UtcNow.ToString('o')
    [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8), $utf8)
    Write-Host "Import manifest: $manifestPath"
}
