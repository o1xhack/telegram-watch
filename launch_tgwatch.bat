@echo off
setlocal

cd /d "%~dp0"

set "USE_CONDA=0"
set "PY_CMD="

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

%PY_CMD% -m tgwatch gui --config config.toml

endlocal
