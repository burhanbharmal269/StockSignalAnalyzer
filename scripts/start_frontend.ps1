# StockSignalAnalyzer — Start Frontend
# Usage: .\scripts\start_frontend.ps1

Write-Host "Starting Next.js frontend on http://localhost:3000..." -ForegroundColor Cyan
cd "D:\StockSignalAnalyzer\frontend"
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
$env:NEXT_PUBLIC_WS_URL  = "ws://localhost:8000"
$env:BACKEND_URL         = "http://localhost:8000"
npm run dev
