# Project Halcyon — allow LAN clients to connect to Halcyon platform & match servers.
# Idempotent: checks for existing rule first. Run as admin.
$ErrorActionPreference = "Stop"
$ruleName = "Halcyon LAN Platform & Match Stack"
$ports = @("80", "443", "8080", "8443", "7100", "7101", "7102", "2112", "2113", "2114")

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Firewall rule already exists: $ruleName"
    exit 0
}

New-NetFirewallRule -DisplayName $ruleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $ports `
    -Description "Allow LAN devices/emulators to connect to Halcyon game servers"

Write-Host "Firewall rule installed successfully for ports: $($ports -join ', ')"
