# UniAgent Hub v3.0 six-minute defense technical rehearsal
# Runs normal / rejected / modify branches sequentially with reset between them.
# Speech rehearsal is manual; this script only validates the technical sequence.
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'
$results = @()

foreach ($mode in @('approved', 'rejected', 'modify')) {
  & powershell -ExecutionPolicy Bypass -File (Join-Path $root 'demo\reset.ps1') *> $null
  $sw = [Diagnostics.Stopwatch]::StartNew()
  & $py -m demo.irrigation_approval --decision $mode *> (Join-Path $root "data\demo_runs\rehearse6_$mode.log")
  $code = $LASTEXITCODE
  $sw.Stop()
  $results += [pscustomobject]@{
    branch = $mode
    exit = $code
    seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1)
  }
}

$results | Format-Table -AutoSize
$pass = ($results | Where-Object { $_.exit -eq 0 }).Count
Write-Host "TECHNICAL REHEARSAL: $pass / 3 branches passed"
if ($pass -ne 3) { exit 1 }
exit 0
