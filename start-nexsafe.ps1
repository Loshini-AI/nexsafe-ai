$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Join-Path $ProjectRoot "backend"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$PythonPath = Join-Path $ProjectRoot ".venv-backend311\Scripts\python.exe"
$EnvPath = Join-Path $ProjectRoot ".env"
$LogRoot = Join-Path $env:LOCALAPPDATA "NexSafeAI\logs"

function New-RandomSecret {
    $bytes = New-Object "System.Byte[]" 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
        return -join ($bytes | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $generator.Dispose()
    }
}

function Initialize-Environment {
    if (Test-Path -LiteralPath $EnvPath) {
        return
    }

    $databasePath = (Join-Path $ProjectRoot "data\nexsafe.db").Replace("\", "/")
    $contents = @"
DATABASE_URL=sqlite+aiosqlite:///$databasePath
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=$(New-RandomSecret)
CAMERA_ENCRYPTION_KEY=$(New-RandomSecret)
ALLOW_REGISTRATION=false
CAMERA_ALLOWED_HOSTS=
UPLOAD_DIR=$((Join-Path $ProjectRoot "data\uploads").Replace("\", "/"))
FRONTEND_ORIGIN=http://localhost:3000,http://127.0.0.1:3000
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
"@

    try {
        [System.IO.File]::WriteAllText(
            $EnvPath,
            $contents + [Environment]::NewLine,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Output "Created local configuration with unique secrets and SQLite storage."
    }
    catch [System.IO.IOException] {
        if (-not (Test-Path -LiteralPath $EnvPath)) {
            throw
        }
    }
}

function Get-AvailablePort([int]$PreferredPort) {
    for ($port = $PreferredPort; $port -lt ($PreferredPort + 20); $port++) {
        $listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Loopback,
            $port
        )
        try {
            $listener.Start()
            return $port
        }
        catch [System.Net.Sockets.SocketException] {
        }
        finally {
            $listener.Stop()
        }
    }

    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    try {
        $listener.Start()
        return $listener.LocalEndpoint.Port
    }
    finally {
        $listener.Stop()
    }
}

function Find-ExistingFrontendPort {
    for ($port = 3000; $port -lt 3020; $port++) {
        try {
            $response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$port/dashboard" `
                -UseBasicParsing `
                -TimeoutSec 2
            if (
                $response.StatusCode -eq 200 -and
                $response.Content -match "<title>NexSafe AI"
            ) {
                return $port
            }
        }
        catch {
        }
    }
    return $null
}

function Restore-ProcessEnvironment([string]$Name, [string]$PreviousValue) {
    if ($null -eq $PreviousValue) {
        Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
    }
    else {
        Set-Item "Env:$Name" $PreviousValue
    }
}

function Get-LogTail([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        return (Get-Content -LiteralPath $Path -Tail 30) -join [Environment]::NewLine
    }
    return "No log file was created."
}

Initialize-Environment

if (-not (Test-Path -LiteralPath $PythonPath)) {
    & (Join-Path $BackendRoot "setup-windows.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Backend setup failed. See the setup output above."
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $FrontendRoot "node_modules"))) {
    Push-Location $FrontendRoot
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend dependency installation failed."
        }
    }
    finally {
        Pop-Location
    }
}

Push-Location $BackendRoot
try {
    & $PythonPath -c "import app.main; print('Backend configuration and imports are valid.')"
    if ($LASTEXITCODE -ne 0) {
        throw "Backend configuration is invalid. Check the local .env file."
    }
    & $PythonPath -m app.backup
    if ($LASTEXITCODE -ne 0) {
        throw "SQLite backup failed; the existing database was not changed."
    }
}
finally {
    Pop-Location
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js and npm are required but npm was not found on PATH."
}

$BackendPort = Get-AvailablePort 8000
$ExistingFrontendPort = Find-ExistingFrontendPort
$reuseFrontend = $null -ne $ExistingFrontendPort
if ($reuseFrontend) {
    $FrontendPort = $ExistingFrontendPort
    Write-Output "Reusing the existing NexSafe frontend on port $FrontendPort."
}
else {
    $FrontendPort = Get-AvailablePort 3000
}
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackendStdout = Join-Path $LogRoot "backend-$stamp.out.log"
$BackendStderr = Join-Path $LogRoot "backend-$stamp.err.log"
$FrontendStdout = Join-Path $LogRoot "frontend-$stamp.out.log"
$FrontendStderr = Join-Path $LogRoot "frontend-$stamp.err.log"

$previousFrontendOrigin = [Environment]::GetEnvironmentVariable(
    "FRONTEND_ORIGIN",
    "Process"
)
$previousUploadDirectory = [Environment]::GetEnvironmentVariable(
    "UPLOAD_DIR",
    "Process"
)
$env:FRONTEND_ORIGIN = "http://localhost:$FrontendPort,http://127.0.0.1:$FrontendPort"
$env:UPLOAD_DIR = Join-Path $ProjectRoot "data\uploads"
try {
    $backendProcess = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList @(
            "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", "$BackendPort"
        ) `
        -WorkingDirectory $BackendRoot `
        -RedirectStandardOutput $BackendStdout `
        -RedirectStandardError $BackendStderr `
        -PassThru
}
finally {
    Restore-ProcessEnvironment "FRONTEND_ORIGIN" $previousFrontendOrigin
    Restore-ProcessEnvironment "UPLOAD_DIR" $previousUploadDirectory
}

$frontendProcess = $null
if (-not $reuseFrontend) {
    $previousApiUrl = [Environment]::GetEnvironmentVariable(
        "NEXT_PUBLIC_API_URL",
        "Process"
    )
    $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$BackendPort"
    try {
        $frontendProcess = Start-Process `
            -FilePath $env:ComSpec `
            -ArgumentList "/c npm run dev -- --hostname 127.0.0.1 --port $FrontendPort" `
            -WorkingDirectory $FrontendRoot `
            -RedirectStandardOutput $FrontendStdout `
            -RedirectStandardError $FrontendStderr `
            -PassThru
    }
    finally {
        Restore-ProcessEnvironment "NEXT_PUBLIC_API_URL" $previousApiUrl
    }
}

$apiUrl = "http://127.0.0.1:$BackendPort"
$frontendUrl = "http://127.0.0.1:$FrontendPort"
$apiReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($backendProcess.HasExited) {
        break
    }
    try {
        $health = Invoke-RestMethod -Uri "$apiUrl/api/health" -TimeoutSec 3
        if ($health.services.database -eq "available") {
            $apiReady = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $apiReady) {
    $apiLogs = (Get-LogTail $BackendStdout) + [Environment]::NewLine +
        (Get-LogTail $BackendStderr)
    if (-not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id
    }
    if ($null -ne $frontendProcess -and -not $frontendProcess.HasExited) {
        Stop-Process -Id $frontendProcess.Id
    }
    throw "Backend failed its database health check. Logs:`n$apiLogs"
}

$frontendReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($null -ne $frontendProcess -and $frontendProcess.HasExited) {
        break
    }
    try {
        $response = Invoke-WebRequest -Uri "$frontendUrl/dashboard" -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            $frontendReady = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $frontendReady) {
    $frontendLogs = (Get-LogTail $FrontendStdout) + [Environment]::NewLine +
        (Get-LogTail $FrontendStderr)
    if (-not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id
    }
    if ($null -ne $frontendProcess -and -not $frontendProcess.HasExited) {
        Stop-Process -Id $frontendProcess.Id
    }
    throw "Frontend failed its HTTP readiness check. Logs:`n$frontendLogs"
}

Write-Output "NexSafe AI is ready."
Write-Output "Website: $frontendUrl/dashboard"
Write-Output "API health: $apiUrl/api/health"
$frontendProcessId = if ($reuseFrontend) { "existing" } else { $frontendProcess.Id }
Write-Output "Backend PID: $($backendProcess.Id); frontend PID: $frontendProcessId"
Write-Output "Logs: $LogRoot"
Start-Process $frontendUrl
