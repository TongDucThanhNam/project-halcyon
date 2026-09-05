# Project Halcyon — point the SEMC platform hostnames at our local stack.
# Idempotent + tagged; revert with remove_hosts.ps1. Run as admin.
$ErrorActionPreference = "Stop"
$marker = "# project-halcyon (local platform stack)"
$names = @(
  "preauth.superevil.net",
  "preauth.superevilmegacorp.net",
  "platform.superevil.net",
  "platform.superevilmegacorp.net",
  "gamefeeds.superevilmegacorp.net",
  "my.superevilmegacorp.net",
  "rpc.kindred-live.net"
)
$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
$content = [System.IO.File]::ReadAllLines($hostsPath)
if ($content -contains $marker) { Write-Host "already installed"; exit 0 }
attrib -r -h -s $hostsPath
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine()
[void]$sb.AppendLine($marker)
foreach ($n in $names) { [void]$sb.AppendLine("127.0.0.1 $n") }
[void]$sb.AppendLine("# end project-halcyon")
[System.IO.File]::AppendAllText($hostsPath, $sb.ToString())
ipconfig /flushdns | Out-Null
Write-Host "hosts installed:"
Get-Content $hostsPath | Select-String "project-halcyon|127.0.0.1 (preauth|platform|gamefeeds|my\.|rpc\.)"
