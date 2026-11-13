$ErrorActionPreference = "Stop"

$BackendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $BackendRoot
$VenvPath = Join-Path $ProjectRoot ".venv-backend311"
$PythonPath = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python Launcher (py.exe) was not found. Install Python 3.11 and enable the launcher."
}

if (-not (Test-Path $PythonPath)) {
    & py -3.11 -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the Python 3.11 environment at $VenvPath."
    }
}

Push-Location $BackendRoot
try {
    & $PythonPath -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Could not update pip in $VenvPath."
    }
    & $PythonPath -m pip install -r requirements.txt -r test-requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Backend dependency installation failed."
    }
    & $PythonPath -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "Installed backend dependencies have conflicts."
    }
    & $PythonPath -c "import os; os.environ['JWT_SECRET']='test-only-jwt-secret-with-more-than-32-characters'; os.environ['CAMERA_ENCRYPTION_KEY']='test-only-camera-key-with-more-than-32-chars'; import app.main, alembic, asyncpg, cv2, fastapi, httpx, redis, sqlalchemy; print('Backend imports passed; vision checkpoints remain optional.')"
    if ($LASTEXITCODE -ne 0) {
        throw "Backend import verification failed."
    }
    & $PythonPath -m unittest discover -s tests -p "test_*.py" -v
    if ($LASTEXITCODE -ne 0) {
        throw "Backend unit tests failed."
    }
}
finally {
    Pop-Location
}

Write-Output "Backend environment ready: $PythonPath"
