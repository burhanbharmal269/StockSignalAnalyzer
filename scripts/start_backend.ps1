# StockSignalAnalyzer — Start Backend Server
# Usage: .\scripts\start_backend.ps1

$pgBin = "$env:USERPROFILE\scoop\apps\postgresql\current\bin"
$pgData = "$env:USERPROFILE\scoop\apps\postgresql\current\data"

Write-Host "Starting PostgreSQL..." -ForegroundColor Cyan
& "$pgBin\pg_ctl.exe" -D "$pgData" -l "$pgData\postgresql.log" start 2>&1 | Out-Null
Start-Sleep -Seconds 2

# Load .env
if (Test-Path "D:\StockSignalAnalyzer\.env") {
    Get-Content "D:\StockSignalAnalyzer\.env" | Where-Object { $_ -match "^\s*[^#].*=.*" } | ForEach-Object {
        $parts = $_ -split "=", 2
        if ($parts.Length -eq 2) {
            $key = $parts[0].Trim()
            $val = $parts[1].Trim()
            [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
}

$env:PYTHONPATH = "D:\StockSignalAnalyzer\src"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "Starting backend on http://0.0.0.0:8000..." -ForegroundColor Cyan
cd "D:\StockSignalAnalyzer\src"
uvicorn "app:create_app" --factory --host 0.0.0.0 --port 8000 --log-level info
