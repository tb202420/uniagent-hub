<#
.SYNOPSIS
    UniAgent Hub 一键演示启动（P1-P6 自动化）。

.DESCRIPTION
    一条命令拉起完整演示环境，无需任何手动配置：
      1. Hub 核心网关（默认 8020，规避本机 8000 被 VirtualBox Manager 占用）
      2. 温度模拟器（--init-temp 31，保证 >28°C 触发 office_cooling 工作流）
      3. 空调模拟器 + 温室灌溉节点模拟器（写操作闭环；--init-soil 25 触发 smart_irrigation）
      4. 审计 Dashboard（18080）
      5. 自动执行 get_weather 预热 + 就绪检查（scripts/demo_warmup.py）
      6. -Ollama 时额外预热本地模型（scripts/ollama_warmup.py，加载权重 + 常驻显存）

    默认每个组件独立控制台窗口（便于现场演示"多设备协同"观感）；
    -LogToFile 改为写 logs/<组件>.log（彩排 / 无人值守自检用）。

.PARAMETER Offline
    断网降级模式：改用本地 MQTT broker（amqtt）+ 本地 Mock 天气 API，
    并自动设置 HUB_MQTT_BROKER / HUB_REST_BASE_URL_OVERRIDE /
    HUB_REST_ALLOWED_PRIVATE_HOSTS 三个环境变量。

.PARAMETER Ollama
    预热本地 Ollama 模型（演示含 LLM 环节时必须）：
    检查服务与模型 → 用与 Agent 一致的 num_ctx 发一次请求加载权重 →
    keep_alive=-1 保持常驻显存，避免现场首次调用卡顿。
    预热失败只告警不中断（LLM 环节会自动降级为脚本模式）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1
    powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Ollama
    powershell -ExecutionPolicy Bypass -File scripts\demo_start.ps1 -Offline -Ollama -LogToFile
#>
[CmdletBinding()]
param(
    [int]$Port = 8020,
    [double]$InitTemp = 31,
    [double]$InitSoil = 25,
    [int]$DashboardPort = 18080,
    [int]$MockPort = 8899,
    [int]$LocalBrokerPort = 1883,
    [string]$Broker = "",
    [switch]$Offline,
    [switch]$Ollama,
    [string]$OllamaModel = "gemma4local:latest",
    [int]$OllamaNumCtx = 16384,
    [switch]$LogToFile,
    [switch]$NoDashboard,
    [double]$WarmupTimeout = 60
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "main.py"))) {
    throw "未找到仓库根目录（main.py），请确认脚本位于 scripts/ 下：$Root"
}

# ---- Python 解释器解析（本机 PATH 上的 python 是坏的 Store shim）----
function Resolve-Python {
    if ($env:HUB_PYTHON -and (Test-Path $env:HUB_PYTHON)) {
        return @{ File = $env:HUB_PYTHON; Prefix = @() }
    }
    $known = Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"
    if (Test-Path $known) {
        return @{ File = $known; Prefix = @() }
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @{ File = $py.Source; Prefix = @("-3") }
    }
    throw "未找到可用 Python。请设置环境变量 HUB_PYTHON 指向 python.exe。"
}

$Py = Resolve-Python
$PythonExe = $Py.File
$PythonPre = $Py.Prefix

function Invoke-Py {
    param([string[]]$Arguments)
    & $PythonExe @($PythonPre + $Arguments)
}

function Test-PortFree {
    param([int]$P)
    $conn = Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue
    return ($null -eq $conn)
}

$LogDir = Join-Path $Root "logs"
if ($LogToFile) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

$Components = @()

function Start-Component {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [string]$Port = "-"
    )
    $allArgs = $PythonPre + $Arguments
    $p = $null
    if ($LogToFile) {
        $out = Join-Path $LogDir "$Name.log"
        $err = Join-Path $LogDir "$Name.err.log"
        $p = Start-Process -FilePath $PythonExe -ArgumentList $allArgs `
            -WorkingDirectory $Root -PassThru -NoNewWindow `
            -RedirectStandardOutput $out -RedirectStandardError $err
    }
    else {
        $p = Start-Process -FilePath $PythonExe -ArgumentList $allArgs `
            -WorkingDirectory $Root -PassThru
    }
    $script:Components += [pscustomobject]@{
        Name = $Name; Port = $Port; Pid = $p.Id; Status = "已启动"
    }
    Write-Host ("  [启动] {0,-14} pid={1}" -f $Name, $p.Id) -ForegroundColor Cyan
    return $p
}

# Ollama 预热结果登记到汇总表（非组件进程，只登记状态）
function Add-ExternalStatus {
    param([string]$Name, [string]$Port, [string]$Status)
    $script:Components += [pscustomobject]@{
        Name = $Name; Port = $Port; Pid = "-"; Status = $Status
    }
}

Write-Host ""
Write-Host "=== UniAgent Hub 一键演示启动 ===" -ForegroundColor Green
Write-Host ("  仓库: {0}" -f $Root)
Write-Host ("  Python: {0} {1}" -f $PythonExe, ($PythonPre -join " "))
Write-Host ("  模式: {0}" -f $(if ($Offline) { "断网降级（本地 broker + Mock API）" } else { "在线（公共 broker + open-meteo）" }))
if ($Ollama) {
    Write-Host ("  本地 LLM: 预热 {0}（num_ctx={1}）" -f $OllamaModel, $OllamaNumCtx)
}
Write-Host ""

# 步骤总数：含 -Ollama 时多一步 LLM 预热
$totalSteps = if ($Ollama) { 7 } else { 6 }

# ---- 端口预检 ----
$needPorts = @($Port)
if (-not $NoDashboard) { $needPorts += $DashboardPort }
if ($Offline) { $needPorts += $LocalBrokerPort; $needPorts += $MockPort }
$occupied = @()
foreach ($p in $needPorts) { if (-not (Test-PortFree $p)) { $occupied += $p } }
if ($occupied.Count -gt 0) {
    Write-Host ("[错误] 端口被占用: {0}" -f ($occupied -join ", ")) -ForegroundColor Red
    Write-Host "       可用 -Port / -DashboardPort 指定其他端口；或先关闭占用进程：" -ForegroundColor Yellow
    Write-Host "       Get-NetTCPConnection -LocalPort <端口> -State Listen | Select OwningProcess" -ForegroundColor Yellow
    exit 1
}
Write-Host ("  [预检] 端口空闲: {0}" -f ($needPorts -join ", ")) -ForegroundColor DarkGray

# ---- 环境变量（在线模式显式清空，避免继承到旧值）----
$effectiveBroker = $Broker
if ($Offline) {
    $env:HUB_MQTT_BROKER = "mqtt://127.0.0.1:$LocalBrokerPort"
    $env:HUB_REST_BASE_URL_OVERRIDE = "http://127.0.0.1:$MockPort"
    $env:HUB_REST_ALLOWED_PRIVATE_HOSTS = "127.0.0.1"
    $effectiveBroker = $env:HUB_MQTT_BROKER
}
else {
    Remove-Item Env:HUB_REST_BASE_URL_OVERRIDE -ErrorAction SilentlyContinue
    Remove-Item Env:HUB_REST_ALLOWED_PRIVATE_HOSTS -ErrorAction SilentlyContinue
    if ($Broker) { $env:HUB_MQTT_BROKER = $Broker; $effectiveBroker = $Broker }
    else { $effectiveBroker = "mqtt://broker.emqx.io:1883" }
    $env:HUB_MQTT_BROKER = $effectiveBroker
}
Write-Host ("  [MQTT] {0}" -f $effectiveBroker) -ForegroundColor DarkGray
if ($Offline) {
    Write-Host ("  [REST] {0} (SSRF 白名单: 127.0.0.1)" -f $env:HUB_REST_BASE_URL_OVERRIDE) -ForegroundColor DarkGray
}
Write-Host ""

# ---- 1) 降级组件（仅 Offline）----
if ($Offline) {
    Write-Host ("[1/$totalSteps] 本地降级组件") -ForegroundColor White
    Start-Component -Name "broker" -Port $LocalBrokerPort -Arguments @(
        "-u", "-m", "scripts.dev_mqtt_broker", "--port", "$LocalBrokerPort") | Out-Null
    Start-Component -Name "mock_weather" -Port $MockPort -Arguments @(
        "-u", "-m", "scripts.mock_weather_api", "--port", "$MockPort") | Out-Null
    Start-Sleep -Seconds 2
}
else {
    Write-Host ("[1/$totalSteps] 在线模式：使用公共 broker（跳过本地降级组件）") -ForegroundColor DarkGray
}

# ---- 2) Hub 核心 ----
Write-Host "[2/$totalSteps] Hub 核心网关" -ForegroundColor White
# P0-BE-2：为本次演示生成一次性 Bearer Token（网关鉴权 + 服务端权限裁决）。
# 客户端脚本（warmup / agent / dashboard）读取 HUB_API_TOKEN 自动携带。
if (-not $env:HUB_API_TOKEN) {
    $env:HUB_API_TOKEN = -join ((48..57) + (97..102) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
}
Write-Host ("  Bearer Token（本次演示）: {0}" -f $env:HUB_API_TOKEN) -ForegroundColor DarkGray
$hubArgs = @("-u", "main.py", "--port", "$Port", "--host", "127.0.0.1")
if ($Broker) { $hubArgs += @("--broker", $Broker) }
Start-Component -Name "hub" -Port $Port -Arguments $hubArgs | Out-Null

# 等待 /healthz 就绪
$healthUrl = "http://127.0.0.1:$Port/healthz"
$deadline = (Get-Date).AddSeconds($WarmupTimeout)
$hubReady = $false
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        if ($r.status -eq "ok") { $hubReady = $true; break }
    }
    catch { Start-Sleep -Milliseconds 500 }
}
if ($hubReady) {
    Write-Host ("  [就绪] Hub {0} 健康检查通过，注册 {1} 个工具" -f $healthUrl, $r.tools) -ForegroundColor Green
}
else {
    Write-Host ("  [警告] Hub {0} 在 {1}s 内未就绪，请查看窗口/hub.log" -f $healthUrl, $WarmupTimeout) -ForegroundColor Red
}

# ---- 3) 温度模拟器（固定初始温度）----
Write-Host "[3/$totalSteps] 温度模拟器（--init-temp $InitTemp）" -ForegroundColor White
Start-Component -Name "sim_temp" -Arguments @(
    "-u", "-m", "adapters.mqtt_adapter.simulator",
    "--broker", $effectiveBroker, "--init-temp", "$InitTemp") | Out-Null

# ---- 4) 空调模拟器 + 温室灌溉节点模拟器 ----
Write-Host "[4/$totalSteps] 空调 / 温室模拟器" -ForegroundColor White
Start-Component -Name "sim_ac" -Arguments @(
    "-u", "-m", "adapters.mqtt_adapter.sim_ac",
    "--broker", $effectiveBroker) | Out-Null
Start-Component -Name "sim_esp32" -Arguments @(
    "-u", "-m", "adapters.mqtt_adapter.sim_esp32_greenhouse",
    "--broker", $effectiveBroker, "--init-soil", "$InitSoil") | Out-Null

Start-Sleep -Seconds 3   # 等设备注册（retain 消息）+ 状态上报

# ---- 5) 审计 Dashboard ----
if (-not $NoDashboard) {
    Write-Host "[5/$totalSteps] 审计 Dashboard" -ForegroundColor White
    Start-Component -Name "dashboard" -Port $DashboardPort -Arguments @(
        "-u", "-m", "web.audit_dashboard",
        "--hub", "http://127.0.0.1:$Port", "--port", "$DashboardPort") | Out-Null
    Start-Sleep -Seconds 2
}
else {
    Write-Host "[5/$totalSteps] 跳过 Dashboard（-NoDashboard）" -ForegroundColor DarkGray
}

# ---- 6) 预热 + 就绪检查 ----
$totalSteps = if ($Ollama) { 7 } else { 6 }
Write-Host ("[6/{0}] 预热 get_weather + 就绪检查" -f $totalSteps) -ForegroundColor White
Invoke-Py @("-m", "scripts.demo_warmup", "--url", "http://127.0.0.1:$Port",
    "--timeout", "$WarmupTimeout")
$warmupCode = $LASTEXITCODE

# ---- 7) 本地 LLM 预热（仅 -Ollama）----
$ollamaCode = 0
if ($Ollama) {
    Write-Host ("[7/{0}] 本地 LLM 预热（Ollama）" -f $totalSteps) -ForegroundColor White
    # keep_alive=-1 供后续从本 shell 启动的进程继承；真正的常驻由预热请求内的
    # keep_alive 参数保证（Ollama 服务已在运行时，环境变量不影响它）
    $env:OLLAMA_KEEP_ALIVE = "-1"
    $env:OLLAMA_THINK = "0"
    Invoke-Py @("-m", "scripts.ollama_warmup", "--model", $OllamaModel,
        "--num-ctx", "$OllamaNumCtx")
    $ollamaCode = $LASTEXITCODE
    if ($ollamaCode -ne 0) {
        Add-ExternalStatus -Name "ollama_llm" -Port "11434" -Status "未就绪(降级)"
        Write-Host "  [警告] 本地 LLM 未就绪 —— 演示时 LLM 环节将自动降级为脚本模式（不失演示）" -ForegroundColor Yellow
    }
    else {
        Add-ExternalStatus -Name "ollama_llm" -Port "11434" -Status "已预热"
    }
    Write-Host "  [提醒] 请确认 Ollama 桌面版已关闭自动更新（设置 → 自动更新），" -ForegroundColor DarkYellow
    Write-Host "         否则演示时可能后台下载更新包导致服务重启、模型被卸载。" -ForegroundColor DarkYellow
}

# ---- 汇总 ----
Write-Host ""
Write-Host "=== 启动汇总 ===" -ForegroundColor Green
$Components | Format-Table -AutoSize Name, Port, Pid, Status | Out-Host
if ($warmupCode -eq 0 -and $ollamaCode -eq 0) {
    Write-Host "全部就绪 —— 可以开始 5 分钟演示。" -ForegroundColor Green
}
elseif ($warmupCode -eq 0) {
    Write-Host "Hub 侧全部就绪；本地 LLM 未就绪（LLM 环节会自动降级为脚本模式）。" -ForegroundColor Yellow
}
else {
    Write-Host "存在未就绪项，请查看上方 [warmup] 输出与 logs/*.log。" -ForegroundColor Red
}
Write-Host ""
Write-Host "演示地址：" -ForegroundColor White
Write-Host ("  Hub      http://127.0.0.1:{0}/healthz" -f $Port)
if (-not $NoDashboard) { Write-Host ("  审计面板 http://127.0.0.1:{0}/" -f $DashboardPort) }
if ($LogToFile) { Write-Host ("  日志目录 {0}" -f $LogDir) }
Write-Host ""
Write-Host "Agent 命令（演示时按幕执行）：" -ForegroundColor White
Write-Host ("  脚本模式  python -m agent.llm_agent --script --url http://127.0.0.1:{0}" -f $Port)
if ($Ollama) {
    Write-Host ("  LLM 模式  python -m agent.llm_agent --ollama --url http://127.0.0.1:{0}" -f $Port)
}
Write-Host ""
Write-Host "停止演示：关闭各组件的控制台窗口；或执行" -ForegroundColor DarkGray
$pids = $Components | Where-Object { $_.Pid -match '^\d+$' } | Select-Object -ExpandProperty Pid
if ($pids) {
    Write-Host ("  {0} | Stop-Process" -f ($pids -join ",")) -ForegroundColor DarkGray
}

# 退出码取两者较差值：Hub 就绪与否是硬指标；LLM 未就绪只影响加分环节
if ($warmupCode -ne 0) { exit $warmupCode }
exit $ollamaCode
