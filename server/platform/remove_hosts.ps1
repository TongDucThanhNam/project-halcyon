# Project Halcyon — remove the local stack's hosts entries. Run as admin.
$ErrorActionPreference = "Stop"
$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
$lines = Get-Content $hostsPath
$keep = $true
$out = New-Object System.Collections.Generic.List[string]
foreach ($line in $lines) {
  if ($line -match "^# project-halcyon") { $keep = $false; continue }
  if ($line -match "^# end project-halcyon") { $keep = $true; continue }
  if ($keep) { $out.Add($line) }
}
Set-Content $hostsPath $out
ipconfig /flushdns | Out-Null
Write-Host "hosts entries removed"
