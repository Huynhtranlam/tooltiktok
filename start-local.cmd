@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
if errorlevel 1 goto path_error

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
  "%VENV_PY%" -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
  if not errorlevel 1 goto check_deps
)

echo Dang tao lai moi truong Python cho may nay...
set "BASE_PY="
py -3.12 -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
if not errorlevel 1 set "BASE_PY=py -3.12"
if not defined BASE_PY (
  py -3 -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
  if not errorlevel 1 set "BASE_PY=py -3"
)
if not defined BASE_PY (
  python -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
  if not errorlevel 1 set "BASE_PY=python"
)
if not defined BASE_PY goto python_error
%BASE_PY% -m venv ".venv"
if errorlevel 1 goto venv_error
"%VENV_PY%" -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
if errorlevel 1 goto venv_error

:check_deps
if exist ".venv\requirements.installed" (
  fc /b "requirements.txt" ".venv\requirements.installed" >nul 2>&1
  if not errorlevel 1 (
    "%VENV_PY%" -c "import flask, waitress, pip" >nul 2>&1
    if not errorlevel 1 goto run
  )
)
echo Dang cai thu vien cho LiveLedger. Lan dau co the mat vai phut...
"%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 "%VENV_PY%" -m ensurepip --upgrade
if errorlevel 1 goto pip_error
"%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto install_error
copy /y "requirements.txt" ".venv\requirements.installed" >nul

:run
echo Dang mo LiveLedger...
"%VENV_PY%" local.py %*
set "APP_EXIT=%errorlevel%"
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%

:path_error
echo Khong mo duoc thu muc chua LiveLedger. Hay chuyen source vao thu muc ban co quyen ghi.
goto failed
:python_error
echo Khong tim thay Python 3.12 tro len tren may nay. Hay cai Python roi chay lai.
goto failed
:venv_error
echo Khong tao duoc .venv trong thu muc nay. Kiem tra quyen ghi va cho trong o dia.
goto failed
:pip_error
echo Python chay duoc nhung khong khoi tao duoc pip. Kiem tra ban cai Python.
goto failed
:install_error
echo Cai thu vien that bai. Xem loi pip ngay phia tren; thuong do ket noi mang hoac quyen ghi.
goto failed
:failed
pause
exit /b 1
