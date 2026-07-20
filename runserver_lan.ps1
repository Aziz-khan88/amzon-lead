$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Automatically find the active Wi-Fi IPv4 address
$wifiIp = Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress

if (-not $wifiIp) {
    # Fallback to any active non-loopback, non-VM IPv4 address if Wi-Fi interface name is different
    $wifiIp = Get-NetIPAddress -AddressFamily IPv4 | 
              Where-Object { $_.InterfaceAlias -notlike "*Loopback*" -and $_.InterfaceAlias -notlike "*VMware*" -and $_.InterfaceAlias -notlike "*VirtualBox*" -and $_.IPAddress -notlike "169.254.*" -and $_.IPAddress -notlike "10.8.*" } | 
              Select-Object -First 1 -ExpandProperty IPAddress
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "             DJANGO LAN RUNNER ACTIVATED                 " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
if ($wifiIp) {
    Write-Host "Your Host Laptop IP Address: " -NoNewline
    Write-Host "$wifiIp" -ForegroundColor Yellow
    Write-Host "Other laptops on the SAME Wi-Fi can access the dashboard at:"
    Write-Host "HTTP Link: http://${wifiIp}:3005/dashboard/" -ForegroundColor Green -BackgroundColor Black
} else {
    Write-Host "Could not automatically determine Wi-Fi IP. Please check `ipconfig`." -ForegroundColor Red
    Write-Host "Other laptops can access at: http://<your-laptop-ip>:3005/dashboard/" -ForegroundColor Yellow
}
Write-Host "----------------------------------------------------------" -ForegroundColor Gray
Write-Host "Starting Django WSGI development server on 0.0.0.0:3005..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C or Ctrl+Break to stop the server." -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

# Determine the correct Python executable to use
$pythonExe = "python"
if (Test-Path "..\.venv\Scripts\python.exe") {
    $pythonExe = "..\.venv\Scripts\python.exe"
}

# Run Django bound to all interfaces
$env:ALLOWED_HOSTS = "*"
& $pythonExe manage.py runserver 0.0.0.0:3005
