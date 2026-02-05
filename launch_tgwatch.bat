@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>&1
  if %errorlevel% == 0 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
)

set "INSTALL_MARKER=.venv\.tgwatch_installed"
if not exist "%INSTALL_MARKER%" (
  ".venv\Scripts\python.exe" -m pip install -e .
  type nul > "%INSTALL_MARKER%"
)

if not exist "config.toml" (
  copy /y config.example.toml config.toml >nul
)

".venv\Scripts\python.exe" -m tgwatch gui --config config.toml

endlocal
