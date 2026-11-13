param(
    [string]$Python = 'C:\Python313\python.exe',
    [ValidateRange(1,730)][int]$LookbackDays = 7,
    [ValidateRange(1,20000)][int]$Budget = 280,
    [ValidateRange(1,1000)][int]$MaxMB = 50,
    [switch]$Execute
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $projectRoot
$refreshArguments = @('-B','-m','Code.intelligence.refresh','--lookback-days',"$LookbackDays",'--budget',"$Budget",'--max-mb',"$MaxMB")
if ($Execute) { $refreshArguments += '--execute' }
& $Python @refreshArguments
exit $LASTEXITCODE
