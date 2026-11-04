@echo off
rem AugeLab 3D bloklari icin GPU servisi + fareyle gezilen Rerun 3D penceresi.
rem venv: DESI3D_VENV ortam degiskeni, yoksa %USERPROFILE%\venvs\desi3d (setup.ps1 olusturur).
rem Rerun penceresi istenmezse --rerun olmadan dogrudan: "%DESI3D_VENV%\Scripts\python.exe" server.py
setlocal
if "%DESI3D_VENV%"=="" set "DESI3D_VENV=%USERPROFILE%\venvs\desi3d"
set "PY=%DESI3D_VENV%\Scripts\python.exe"
if not exist "%PY%" (
  echo Python bulunamadi: %PY%
  echo Once depo kokunde setup.ps1 calistir ya da DESI3D_VENV ayarla.
  pause
  exit /b 1
)
set PYTHONIOENCODING=utf-8
set PYTHONWARNINGS=ignore
set PYTHONUNBUFFERED=1
"%PY%" "%~dp0server.py" --rerun %*
pause
