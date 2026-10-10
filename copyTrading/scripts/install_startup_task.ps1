param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonPath = "python"
)

$resolvedRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$pythonCommand = Get-Command -Name $PythonPath -ErrorAction Stop
$resolvedPython = $pythonCommand.Source
$taskName = "CopyTrade MT5 Launcher"
$launcherCommand = "Set-Location -LiteralPath '$resolvedRoot'; `$env:PYTHONPATH='$resolvedRoot\src'; & '$resolvedPython' -m copytrade.launcher 'config\launcher.json'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$launcherCommand`"" -WorkingDirectory $resolvedRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Menjalankan supervisor copy trade MT5 saat Windows startup" -Force | Out-Null
Write-Output "Scheduled task '$taskName' dibuat untuk $resolvedRoot"
