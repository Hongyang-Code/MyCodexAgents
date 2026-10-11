param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$agentRoot = $PSScriptRoot
& $Python -m venv (Join-Path $agentRoot '.venv')
if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed. Pass -Python with a working interpreter path.' }
& (Join-Path $agentRoot '.venv\Scripts\python.exe') (Join-Path $agentRoot 'run.py') capabilities
