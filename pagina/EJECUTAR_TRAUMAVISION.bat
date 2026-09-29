@echo off
:: ====================================================
:: EJECUTABLE TraumaVision AI
:: ====================================================
:: Doble click en este archivo para correr la aplicacion
:: Se abrira automaticamente en http://localhost:8000
:: ====================================================

echo.
echo ====================================================
echo   🦴 TraumaVision AI - Sistema de Deteccion de Fracturas
echo ====================================================
echo.
echo ⏳ Iniciando aplicacion...
echo.

:: Cambiar a la carpeta del proyecto (la del propio .bat, no una ruta fija)
cd /d "%~dp0"

:: El entorno virtual esta en la carpeta de arriba (TraumaVision\venv)
set PY="%~dp0..\venv\Scripts\python.exe"

:: Verificar que el entorno virtual esta activo
echo ✅ Entorno virtual activado
echo.

:: Instalar dependencias si es necesario (solo tarda la primera vez)
echo 📦 Verificando dependencias...
%PY% -m pip install -r ..\requirements.txt > nul 2>&1

:: Mensaje de éxito
echo ✅ Dependencias verificadas
echo.

echo 🧠 Modelo activo: YOLOv8m sobre GRAZPEDWRI-DX (muneca pediatrica)
echo.

echo 🚀 Iniciando servidor web...
echo.
echo ====================================================
echo   ✅ TraumaVision AI esta corriendo!
echo   📱 Abriendo navegador en: http://localhost:8000
echo   🛑 Para cerrar: Presiona Ctrl+C en esta ventana
echo ====================================================
echo.

:: Esperar un momento para que arranque el servidor
timeout /t 3 > nul

:: Abrir el navegador automáticamente
start "" "http://localhost:8000"

:: Ejecutar la aplicación (esto mantiene la ventana abierta)
%PY% -m app.main

:: Si llega aquí, la app se cerró
echo.
echo 🛑 TraumaVision AI se ha cerrado.
echo.
pause