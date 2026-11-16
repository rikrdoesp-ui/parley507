@echo off
rem Actualizacion automatica (tarea de Windows "Parley507 actualizar", cada 30 min de 10:00 a 01:00).
rem Instalar o reinstalar:  powershell -File tools\instalar_tarea.ps1
cd /d "%~dp0.."
echo ==== %date% %time% >> "%USERPROFILE%\sports-data\actualizar_auto.log"
uv run actualizar >> "%USERPROFILE%\sports-data\actualizar_auto.log" 2>&1
