@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv >nul 2>&1
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 (
    echo Khong tao duoc moi truong Python. Hay cai Python 3.12 tro len.
    pause
    exit /b 1
  )
)
if exist ".venv\requirements.installed" (
  fc /b "requirements.txt" ".venv\requirements.installed" >nul 2>&1
  if not errorlevel 1 goto run
)
echo Dang chuan bi LiveLedger. Lan dau co the mat vai phut...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo Khong cai duoc thu vien can thiet. Kiem tra ket noi mang roi thu lai.
  pause
  exit /b 1
)
copy /y "requirements.txt" ".venv\requirements.installed" >nul
:run
echo Dang mo LiveLedger...
".venv\Scripts\python.exe" local.py %*
if errorlevel 1 pause
