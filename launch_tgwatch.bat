@echo off
setlocal

cd /d "%~dp0"

set "USE_CONDA=0"
set "PY_CMD="
if "%TGWATCH_GUI_HOST%"=="" (
  set "GUI_HOST=127.0.0.1"
) else (
  set "GUI_HOST=%TGWATCH_GUI_HOST%"
)
if "%TGWATCH_GUI_PORT%"=="" (
  set "GUI_PORT=8765"
) else (
  set "GUI_PORT=%TGWATCH_GUI_PORT%"
)

where conda >nul 2>&1
if %errorlevel% == 0 (
  for /f "delims=" %%i in ('conda info --base 2^>nul') do set "CONDA_BASE=%%i"
  if defined CONDA_BASE if exist "%CONDA_BASE%\condabin\conda.bat" (
    call "%CONDA_BASE%\condabin\conda.bat" env list | findstr /r /c:"^tgwatch " >nul
    if errorlevel 1 (
      echo [tgwatch] Creating Conda environment: tgwatch
      call "%CONDA_BASE%\condabin\conda.bat" create -y -n tgwatch python=3.11
    ) else (
      echo [tgwatch] Using existing Conda environment: tgwatch
    )
    call "%CONDA_BASE%\condabin\conda.bat" activate tgwatch >nul 2>&1
    if not errorlevel 1 (
      set "USE_CONDA=1"
      set "PY_CMD=python"
      %PY_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
      if errorlevel 1 (
        echo [tgwatch] Conda environment must use Python 3.11+
        exit /b 1
      )
    ) else (
      echo [tgwatch] Conda activate failed, falling back to venv
    )
  )
)

if "%USE_CONDA%"=="1" (
  set "INSTALL_MARKER=.conda-tgwatch-installed"
  if not exist "%INSTALL_MARKER%" (
    %PY_CMD% -m pip install -U pip setuptools wheel
    if errorlevel 1 (
      echo [tgwatch] Warning: failed to upgrade pip/setuptools/wheel; continuing.
    )
    %PY_CMD% -m pip install -e .
    if errorlevel 1 (
      echo [tgwatch] Error: project install failed. Check network/proxy/pip index settings.
      exit /b 1
    )
    type nul > "%INSTALL_MARKER%"
  )
  echo [tgwatch] Environment source: conda (tgwatch)
) else (
  if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>&1
    if %errorlevel% == 0 (
      py -3.11 -m venv .venv
    ) else (
      python -m venv .venv
    )
  )
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
  if errorlevel 1 (
    echo [tgwatch] venv Python must be 3.11+
    exit /b 1
  )

  set "INSTALL_MARKER=.venv\.tgwatch_installed"
  if not exist "%INSTALL_MARKER%" (
    ".venv\Scripts\python.exe" -m pip install -U pip setuptools wheel
    if errorlevel 1 (
      echo [tgwatch] Warning: failed to upgrade pip/setuptools/wheel; continuing.
    )
    ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 (
      echo [tgwatch] Error: project install failed. Check network/proxy/pip index settings.
      exit /b 1
    )
    type nul > "%INSTALL_MARKER%"
  )
  set "PY_CMD=.venv\Scripts\python.exe"
  echo [tgwatch] Environment source: venv (.venv)
)

if not exist "config.toml" (
  copy /y config.example.toml config.toml >nul
)

call :recover_gui_port
if errorlevel 1 exit /b 1

%PY_CMD% -m tgwatch gui --config config.toml --host %GUI_HOST% --port %GUI_PORT%

endlocal
exit /b 0

:recover_gui_port
setlocal EnableDelayedExpansion
set "PIDS="
for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /r /c:":%GUI_PORT% .*LISTENING"') do (
  echo !PIDS! | findstr /w "%%P" >nul || set "PIDS=!PIDS! %%P"
)
if "!PIDS!"=="" (
  endlocal & exit /b 0
)

echo [tgwatch] Port %GUI_PORT% is in use. Attempting recovery...
for %%P in (!PIDS!) do (
  set "PROC=unknown"
  for /f "tokens=1,* delims=:" %%A in ('tasklist /fi "PID eq %%P" /fo list ^| findstr /b /c:"Image Name:"') do (
    set "PROC=%%B"
  )
  echo [tgwatch] Stopping PID %%P!PROC!
  taskkill /PID %%P /T /F >nul 2>&1
)

timeout /t 1 /nobreak >nul
for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /r /c:":%GUI_PORT% .*LISTENING"') do (
  echo [tgwatch] Error: port %GUI_PORT% is still in use by PID %%P.
  endlocal & exit /b 1
)

echo [tgwatch] Port %GUI_PORT% recovered.
endlocal & exit /b 0
