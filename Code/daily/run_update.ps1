param(
    [string]$Python = 'C:\Python313\python.exe',
    [ValidateRange(1,365)][int]$LookbackDays = 7,
    [ValidateRange(2,14640)][int]$Budget = 280,
    [ValidateRange(1,1000)][int]$MaxMB = 50,
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$refreshArgs = @('-B','-m','Code.daily.update','--lookback-days',"$LookbackDays",'--budget',"$Budget",'--max-mb',"$MaxMB")
if ($Execute) { $refreshArgs += '--execute' }
& $Python @refreshArgs
exit $LASTEXITCODE
