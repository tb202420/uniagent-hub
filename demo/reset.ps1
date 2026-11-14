# 演示重置（Windows）：清理两次演示之间的进程与状态，目标 5 秒内完成
# 用法：powershell -ExecutionPolicy Bypass -File demo\reset.ps1
$root = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $root 'data\demo_runs'

if (Test-Path $runDir) {
  Get-ChildItem $runDir -Filter 'irrigation_approval_*.pids' | ForEach-Object {
    Get-Content $_.FullName | ForEach-Object {
      $procId = $_.Trim()
      if ($procId) { Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue }
    }
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
  }
}

# 常驻演示栈（record_start.ps1 启动的 broker/sim/hub/dashboard）
$stack = Join-Path $root 'data\demo_stack.pids'
if (Test-Path $stack) {
  Get-Content $stack | ForEach-Object {
    $procId = $_.Trim()
    if ($procId) { Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue }
  }
  Remove-Item $stack -Force -ErrorAction SilentlyContinue
  Write-Host '[reset] 常驻演示栈已停止'
}

Get-ChildItem (Join-Path $root 'data') -Filter 'demo_irrigation.db*' -ErrorAction SilentlyContinue |
  Remove-Item -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $root 'data\demo_irrigation_audit.jsonl') -Force -ErrorAction SilentlyContinue

Write-Host '[reset] 演示进程已清理，审批状态/演示库/审计已重置（证据日志保留在 data/demo_runs）'
