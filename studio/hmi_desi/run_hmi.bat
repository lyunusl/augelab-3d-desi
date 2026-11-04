@echo off
setlocal
if not defined AUGELAB_STUDIO_PYTHON set "AUGELAB_STUDIO_PYTHON=%LOCALAPPDATA%\Programs\AugeLab Studio\Python\python.exe"
if not exist "%AUGELAB_STUDIO_PYTHON%" (
    echo Studio Python bulunamadi. AUGELAB_STUDIO_PYTHON degiskenini ayarlayin.
    pause
    exit /b 1
)
"%AUGELAB_STUDIO_PYTHON%" "%~dp0hmi_start.py"
if errorlevel 1 (
    pause
    exit /b 1
)
