param(
    [int]$Port = 8001,
    [switch]$New,
    [switch]$NoBrowser,
    [switch]$FreezeClock
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw '未找到项目虚拟环境，请先按 README.md 安装 Python 依赖。'
}
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath 'web/node_modules')) {
        & npm.cmd --prefix web ci
        if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
    }
    & npm.cmd --prefix web run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
    $launchArgs = @('-X', 'utf8', '-m', 'examples.simulation_server', '--port', "$Port")
    if ($New) { $launchArgs += '--new' }
    if ($NoBrowser) { $launchArgs += '--no-browser' }
    if ($FreezeClock) { $launchArgs += '--freeze-clock' }
    & $python @launchArgs
    if ($LASTEXITCODE -ne 0) { throw "演示启动失败，退出码：$LASTEXITCODE" }
}
finally {
    Pop-Location
}
