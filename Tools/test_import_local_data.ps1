#Requires -Version 5.1
<# Runs isolated import fixtures under TEMP; keeps all fixtures/manifests. #>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$importer = Join-Path $PSScriptRoot 'import_local_data.ps1'
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('halcyon-import-test-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testRoot
$results = New-Object 'System.Collections.Generic.List[object]'

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Write-Fixture([string]$Relative, [string]$Contents) {
    $path = Join-Path $script:testRoot $Relative
    $null = New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force
    [IO.File]::WriteAllText($path, $Contents)
}
function Read-LastManifest([string]$Root) {
    $path = Get-ChildItem -LiteralPath (Join-Path $Root 'manifests') -Filter '*.json' |
        Sort-Object Name | Select-Object -Last 1
    return Get-Content -LiteralPath $path.FullName -Raw | ConvertFrom-Json
}
function Assert-Refused([scriptblock]$Action, [string]$Expected) {
    $message = $null
    try { & $Action } catch { $message = $_.Exception.Message }
    Assert-True ($null -ne $message -and $message -like "*$Expected*") "Expected refusal '$Expected', got '$message'"
}
try {
    Write-Fixture 'source\one.txt' 'owned input'
    Write-Fixture 'source\nested\two.txt' 'second input'
    $source = Join-Path $testRoot 'source'
    $local = Join-Path $testRoot 'local'
    & $importer -GameSource $source -LocalRoot $local
    $manifest = Read-LastManifest $local
    Assert-True ($manifest.status -eq 'COMPLETE' -and $manifest.files.Count -eq 2) 'Copy manifest failed'
    Assert-True (@($manifest.files | Where-Object status -ne 'COPIED').Count -eq 0) 'Files were not copied'
    foreach ($file in $manifest.files) {
        $target = Join-Path $local $file.destination
        Assert-True ((Get-FileHash -LiteralPath $target).Hash -eq $file.sha256) 'Manifest SHA256 mismatch'
        Assert-True (Test-Path -LiteralPath $file.source) 'Source was removed'
    }
    $results.Add(@{ name = 'copy_and_manifest'; status = 'PASS' })

    & $importer -GameSource $source -LocalRoot $local
    $manifest = Read-LastManifest $local
    Assert-True (@($manifest.files | Where-Object status -ne 'IDENTICAL').Count -eq 0) 'Identical rerun failed'
    $results.Add(@{ name = 'identical_rerun'; status = 'PASS' })

    Write-Fixture 'source\nested\two.txt' 'changed input'
    Assert-Refused { & $importer -GameSource $source -LocalRoot $local } 'Refusing to overwrite'
    $manifest = Read-LastManifest $local
    Assert-True ($manifest.status -eq 'FAILED' -and $manifest.files.Count -eq 2) 'Partial failure manifest missing'
    Assert-True ((Get-Content -LiteralPath (Join-Path $local 'vainglory\nested\two.txt') -Raw) -eq 'second input') 'Conflict was overwritten'
    $results.Add(@{ name = 'conflict_preserves_destination_and_progress'; status = 'PASS' })

    Assert-Refused { & $importer -GameSource $source -LocalRoot (Join-Path $source 'nested\local') } 'must not overlap'
    Assert-Refused { & $importer -GameSource (Join-Path $local 'vainglory') -LocalRoot $local } 'must not overlap'
    $results.Add(@{ name = 'source_destination_overlap_both_directions'; status = 'PASS' })

    Write-Fixture 'stack\answers.json' '{}'
    Write-Fixture 'stack\platform_key.pem' 'test key placeholder'
    Write-Fixture 'stack\platform_cert.pem' 'test cert placeholder'
    Write-Fixture 'stack\platform.cer' 'test public cert placeholder'
    Write-Fixture 'stack\world_tape.bin' 'test tape placeholder'
    Write-Fixture 'stack\rpc.jsonl' 'must stay outside'
    Write-Fixture 'stack\logs\capture.vgr' 'must stay outside'
    Write-Fixture 'volley\volley.vgr' 'owned volley fixture'
    Write-Fixture 'volley\ignored.txt' 'do not import'
    Write-Fixture 'volley\nested\ignored.vgr' 'do not recurse'
    Write-Fixture 'spawn\spawn.vgr' 'owned spawn fixture'
    Write-Fixture 'research\nested\research.txt' 'owned research fixture'
    $selectedLocal = Join-Path $testRoot 'selected-local'
    & $importer -StackSource (Join-Path $testRoot 'stack') -ResearchSource (Join-Path $testRoot 'research') `
        -VolleySource (Join-Path $testRoot 'volley') -SpawnSource (Join-Path $testRoot 'spawn') -LocalRoot $selectedLocal
    $manifest = Read-LastManifest $selectedLocal
    Assert-True ($manifest.files.Count -eq 8) 'Selective import count mismatch'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $selectedLocal 'runtime\halcyon_stack\rpc.jsonl'))) 'Imported runtime logs'
    Assert-True (Test-Path -LiteralPath (Join-Path $selectedLocal 'research\runtime-corpus\volley.vgr')) 'Missing runtime volley'
    Assert-True (Test-Path -LiteralPath (Join-Path $selectedLocal 'research\runtime-corpus\spawn.vgr')) 'Missing runtime spawn'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $selectedLocal 'research\runtime-corpus\nested'))) 'Recursed VGR source'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $selectedLocal 'research\vg_phaseB'))) 'Runtime records must not imitate original phaseB archive'
    $results.Add(@{ name = 'selective_runtime_and_vgr_import'; status = 'PASS' })

    # Directory junction creation does not require symbolic-link privileges.
    $junction = Join-Path $testRoot 'junction-source'
    $null = New-Item -ItemType Junction -Path $junction -Target $source
    Assert-Refused { & $importer -GameSource $junction -LocalRoot (Join-Path $testRoot 'junction-local') } 'Reparse points'
    $null = New-Item -ItemType Directory -Path (Join-Path $testRoot 'tree-reparse')
    $null = New-Item -ItemType Junction -Path (Join-Path $testRoot 'tree-reparse\link') -Target $source
    Assert-Refused { & $importer -GameSource (Join-Path $testRoot 'tree-reparse') -LocalRoot (Join-Path $testRoot 'tree-local') } 'Reparse points'
    Assert-True ((Read-LastManifest (Join-Path $testRoot 'tree-local')).status -eq 'FAILED') 'Nested reparse failure manifest missing'
    $null = New-Item -ItemType Junction -Path (Join-Path $testRoot 'destination-link') -Target $local
    Assert-Refused { & $importer -GameSource $source -LocalRoot (Join-Path $testRoot 'destination-link') } 'Reparse points'
    $results.Add(@{ name = 'source_nested_and_destination_reparse_refusal'; status = 'PASS' })

    $unignored = Join-Path (Split-Path -Parent $PSScriptRoot) ('unignored-import-test-' + [Guid]::NewGuid().ToString('N'))
    Assert-Refused { & $importer -GameSource $source -LocalRoot $unignored } 'must be ignored by Git'
    Assert-True (-not (Test-Path -LiteralPath $unignored)) 'Unignored destination was created'
    $results.Add(@{ name = 'git_ignore_required_before_creation'; status = 'PASS' })

    # Run the actual script with its default parameter in a TEMP project tree.
    # Only Git's two read-only answers are mocked: no Git repository is created,
    # and the real checkout receives no synthetic payload or output.
    $fakeProject = Join-Path $testRoot 'default-project'
    $fakeTools = Join-Path $fakeProject 'Tools'
    $null = New-Item -ItemType Directory -Path $fakeTools
    $defaultImporter = Join-Path $fakeTools 'import_local_data.ps1'
    Copy-Item -LiteralPath $importer -Destination $defaultImporter
    & {
        $gitCalls = New-Object 'System.Collections.Generic.List[string]'
        function git {
            $arguments = @($args)
            Assert-True ($arguments.Count -ge 3 -and $arguments[0] -eq '-C' -and
                $arguments[1] -eq $fakeProject) 'Default-root Git command used wrong project'
            $command = $arguments[2..($arguments.Count - 1)] -join ' '
            # PowerShell consumes '--' when dispatching to a function.
            Assert-True ($command -in @('check-ignore --quiet Local/', 'ls-files Local/')) "Unexpected mocked Git command: $command"
            $gitCalls.Add($command)
            $global:LASTEXITCODE = 0
        }
        & $defaultImporter -GameSource $source
        Assert-True ($gitCalls.Count -eq 2) 'Default-root import did not check Git boundaries'
    }
    $defaultLocal = Join-Path $fakeProject 'Local'
    $manifest = Read-LastManifest $defaultLocal
    Assert-True ($manifest.local_root -eq $defaultLocal -and $manifest.status -eq 'COMPLETE' -and
        $manifest.files.Count -eq 2) 'Default LocalRoot did not resolve under copied script project'
    $results.Add(@{ name = 'default_local_root_from_script_location'; status = 'PASS' })
} finally {
    $report = [ordered]@{ root = $testRoot; tests = @($results.ToArray()) }
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $testRoot 'test-results.json') -Encoding UTF8
    Write-Host "Import tests: $($results.Count) passed. Artifacts: $testRoot"
}
