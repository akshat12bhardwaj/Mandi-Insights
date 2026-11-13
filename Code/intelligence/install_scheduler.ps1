param(
    [string]$Python = 'C:\Python313\python.exe',
    [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')][string]$TimeIST = '22:30',
    [string]$TaskName = 'MandiInsightsDailyRefresh',
    [switch]$BatchOnly,
    [switch]$ValidateOnly,
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))).Path
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python interpreter not found.' }
$zone = (Get-TimeZone).Id
if ($zone -ne 'India Standard Time') { throw 'This scheduler script requires Windows India Standard Time; no task was installed.' }
Get-Command Register-ScheduledTask -ErrorAction Stop | Out-Null
$arguments = '-B -m Code.intelligence.refresh --execute --lookback-days 7 --budget 280 --max-mb 50'
if ($BatchOnly) { $arguments = '-B -m Code.intelligence.refresh --batch-only' }
$plan = [ordered]@{ task_name=$TaskName; time_ist=$TimeIST; timezone=$zone; executable=$Python; arguments=$arguments; working_directory=$projectRoot; installed=$false }
$action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $projectRoot
$clockTime = [datetime]::ParseExact($TimeIST,'HH:mm',$null)
$nextRun = (Get-Date).Date.AddHours($clockTime.Hour).AddMinutes($clockTime.Minute)
if ($nextRun -le (Get-Date)) { $nextRun = $nextRun.AddDays(1) }
$trigger = New-ScheduledTaskTrigger -Daily -At $nextRun
$plan['next_run_ist'] = $nextRun.ToString('yyyy-MM-dd HH:mm:ss')
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$description = if ($BatchOnly) { 'Mandi Insights local daily forecast publication after date rollover; no download or training.' } else { 'Mandi Insights daily incremental market update; default 22:30 IST is a project schedule, not an upstream publication guarantee.' }
$definition = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $description
if ($ValidateOnly) {
    if ($definition.Actions[0].Execute -ne $Python -or $definition.Actions[0].WorkingDirectory -ne $projectRoot) { throw 'Scheduler action validation failed.' }
    $plan['validation'] = 'Task definition and action constructed successfully; registration not performed.'
}
if ($Install) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw 'Task already exists; inspect it before replacing it.' }
    Register-ScheduledTask -TaskName $TaskName -InputObject $definition | Out-Null
    $plan['installed'] = $true
}
$plan | ConvertTo-Json
