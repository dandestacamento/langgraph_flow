# Starts the MLflow tracking server for this project, on demand.
#
# Usage: run this script whenever you want to test your agent and view
# traces. It does nothing automatically - MLflow will NOT start at login,
# at computer restart, or in the background by itself.
#
# The server is launched via WMI (Win32_Process) rather than Start-Process
# so that it keeps running independently of whatever terminal/session
# launched it (it won't die if that terminal is closed).
#
# To stop the server when you're done testing, run .\stop_mlflow.ps1

$ErrorActionPreference = "Stop"
$projectDir = "C:\Users\dande\Documents\ai_agent-proj\langgraph_flow"
$port = 5000

$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "MLflow already appears to be running on port $port (PID $($existing[0].OwningProcess)). Nothing to do."
    Write-Host "Open http://127.0.0.1:$port to view it."
    exit 0
}

$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$command = "`"$pythonExe`" -m mlflow server --host 127.0.0.1 --port $port --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlruns"

# Launch via WMI so the process is owned by the system's WMI service, not by
# this PowerShell session - it will survive this terminal/session closing.
$startInfo = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine      = "cmd.exe /c `"cd /d $projectDir && $command >> mlflow_stdout.log 2>> mlflow_stderr.log`""
    CurrentDirectory = $projectDir
}

if ($startInfo.ReturnValue -ne 0) {
    Write-Error "Failed to start MLflow server (WMI return code: $($startInfo.ReturnValue))"
    exit 1
}

Write-Host "Starting MLflow server (PID $($startInfo.ProcessId))..."

$upped = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 2
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$port" -UseBasicParsing -TimeoutSec 5 | Out-Null
        $upped = $true
        break
    } catch {
        continue
    }
}

if ($upped) {
    Write-Host "MLflow is up: http://127.0.0.1:$port"
} else {
    Write-Warning "MLflow did not respond within 20s. Check mlflow_stderr.log for details."
}
