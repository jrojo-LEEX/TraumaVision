# ====================================================
# EJECUTABLE TraumaVision AI (PowerShell)
# ====================================================
# Ejecutar con: .\EJECUTAR_TRAUMAVISION.ps1
# o hacer clic derecho > "Ejecutar con PowerShell"
# ====================================================

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  🦴 TraumaVision AI - Sistema de Detección de Fracturas" -ForegroundColor Yellow
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "⏳ Iniciando aplicación..." -ForegroundColor Green

# Cambiar a la carpeta del proyecto (la del propio script, no una ruta fija)
Set-Location $PSScriptRoot

# Verificar que estamos en la carpeta correcta
if (-not (Test-Path "app\main.py")) {
    Write-Host "❌ ERROR: No se encontró el proyecto en la ubicación esperada." -ForegroundColor Red
    Write-Host "   Ubicación actual: $PWD" -ForegroundColor Red
    pause
    exit
}

Write-Host "📁 Proyecto encontrado" -ForegroundColor Green

# El entorno virtual está en la carpeta de arriba (TraumaVision\venv)
$py = Join-Path $PSScriptRoot "..\venv\Scripts\python.exe"
if (Test-Path $py) {
    Write-Host "✅ Entorno virtual encontrado" -ForegroundColor Green
} else {
    Write-Host "❌ ERROR: No se encontró el entorno virtual en TraumaVision\venv." -ForegroundColor Red
    Write-Host "   Ejecuta primero, desde TraumaVision: python -m venv venv" -ForegroundColor Yellow
    pause
    exit
}

Write-Host ""
Write-Host "📦 Verificando dependencias..." -ForegroundColor Yellow
try {
    & $py -m pip install -r ..\requirements.txt --quiet
    Write-Host "✅ Dependencias verificadas" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Advertencia: Problema con dependencias, continuando..." -ForegroundColor Yellow
}

Write-Host "🧠 Modelo activo: YOLOv8m sobre GRAZPEDWRI-DX (muneca pediatrica) | Modo demo: credenciales en la pantalla de login" -ForegroundColor Cyan

Write-Host ""
Write-Host "🚀 Iniciando servidor web..." -ForegroundColor Green
Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host "  ✅ TraumaVision AI está corriendo!" -ForegroundColor Green
Write-Host "  📱 URL: http://localhost:8000" -ForegroundColor Yellow
Write-Host "  🛑 Para cerrar: Presiona Ctrl+C" -ForegroundColor Red
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

# Esperar un momento para que arranque el servidor
Start-Sleep -Seconds 2

# Abrir el navegador automáticamente en segundo plano
Start-Process "http://localhost:8000"

# Ejecutar la aplicación
try {
    & $py -m app.main
} catch {
    Write-Host ""
    Write-Host "❌ ERROR al ejecutar la aplicación:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    pause
}

Write-Host ""
Write-Host "🛑 TraumaVision AI se ha cerrado." -ForegroundColor Yellow
pause