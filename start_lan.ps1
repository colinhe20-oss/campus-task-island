$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$port = 8000

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到项目虚拟环境：$python"
}

$addresses = @(
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -ExpandProperty IPAddress |
        Sort-Object -Unique
)

Write-Host '校园任务岛局域网服务即将启动。'
Write-Host "本机地址：http://127.0.0.1:$port/"
if ($addresses.Count -gt 0) {
    Write-Host '同一局域网内的其他电脑可尝试以下地址：'
    foreach ($address in $addresses) {
        Write-Host "  http://${address}:$port/"
    }
}
if ($addresses.Count -eq 0) {
    Write-Warning '暂时没有检测到可用的局域网 IPv4 地址。连接 Wi-Fi 或网线后可重新运行此脚本。'
}
Write-Host '按 Ctrl+C 停止服务。'

Set-Location -LiteralPath $projectRoot
& $python -m uvicorn campus.app:app --host 0.0.0.0 --port $port
exit $LASTEXITCODE
