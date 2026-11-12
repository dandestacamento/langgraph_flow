# Stops the MLflow tracking server for this project, if it's running.
#
# Usage: run this script when you're done testing and want to free up the
# port / stop the background process.
#
# `mlflow server` internally forks a manager process plus several worker
# processes (uvicorn --workers). Killing only the process bound to the port
# leaves the worker processes running and still serving traffic, so this
# script finds and stops every related process, not just one PID.

$port = 5000

$related = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'mlflow|uvicorn|spawn_main' }

$portOwner = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if (-not $related -and -not $portOwner) {
    Write-Host "MLflow does not appear to be running on port $port."
    exit 0
}

$pids = @()
if ($related) { $pids += $related.ProcessId }
if ($portOwner) { $pids += $portOwner.OwningProcess }
$pids = $pids | Select-Object -Unique

foreach ($procId in $pids) {
    Write-Host "Stopping process PID $procId..."
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 2

$stillUp = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($stillUp) {
    Write-Warning "Port $port is still in use (PID $($stillUp[0].OwningProcess)). Run this script again."
} else {
    Write-Host "Done. MLflow stopped."
}
