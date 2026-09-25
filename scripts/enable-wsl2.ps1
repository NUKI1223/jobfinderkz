# Run from an elevated Windows PowerShell. Does not restart Windows.
# Microsoft: https://learn.microsoft.com/windows/wsl/troubleshooting
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$logPath = Join-Path $PSScriptRoot '..\docs\wsl-repair.log'
Start-Transcript -Path $logPath -Force
try {
    $feature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
    Write-Host "VirtualMachinePlatform: $($feature.State)"
    if ($feature.State -ne 'Enabled') {
        Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
    }
    & bcdedit.exe /set hypervisorlaunchtype auto
    if ($LASTEXITCODE -ne 0) { throw 'Could not enable hypervisor startup.' }
    Write-Host 'Windows configuration updated. Save your work and restart Windows manually.'
    Write-Host 'If WSL2 still fails, check CPU virtualization in BIOS/UEFI.'
} finally {
    Stop-Transcript
}
