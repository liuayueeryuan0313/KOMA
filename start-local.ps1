param([int]$ListenPort = 8080)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { throw 'Python is required. Install Python and cryptography from requirements.txt.' }
if (-not $env:NODE_BIN) {
    $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
    if (-not $nodeCommand) { throw 'Node.js is required.' }
    $env:NODE_BIN = $nodeCommand.Source
}
if (-not $env:DATA_DIR) { $env:DATA_DIR = Join-Path $projectRoot 'data' }
$env:HOST = '127.0.0.1'
$env:PORT = [string]$ListenPort
if (-not $env:PUBLIC_URL) { $env:PUBLIC_URL = "http://127.0.0.1:$ListenPort" }
$env:PYTHONDONTWRITEBYTECODE = '1'
& $pythonCommand.Source (Join-Path $projectRoot 'server.py')
exit $LASTEXITCODE
