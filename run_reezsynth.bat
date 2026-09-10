@echo off
setlocal

rem Always run from the folder containing this launcher.
pushd "%~dp0"
if errorlevel 1 (
    echo ERROR: Could not open the project folder.
    pause
    exit /b 1
)

set "ENV_NAME=reezsynth"
set "DEFAULT_SCRIPT=reezsynth_gui_v04.py"
set "RESULT=0"

rem With no arguments, launch the default GUI.
if "%~1"=="" (
    if not exist "%DEFAULT_SCRIPT%" (
        echo ERROR: Default GUI file not found:
        echo   %DEFAULT_SCRIPT%
        echo.
        echo Edit DEFAULT_SCRIPT in this launcher, or provide a filename:
        echo   run_reezsynth.bat your_gui_file.py
        set "RESULT=1"
        goto finish
    )
) else (
    if not exist "%~1" (
        echo ERROR: Script not found:
        echo   %~1
        set "RESULT=1"
        goto finish
    )
)

rem If the requested Conda environment is already active, use it.
if /I "%CONDA_DEFAULT_ENV%"=="%ENV_NAME%" goto active_environment

rem Conda normally exposes its executable through CONDA_EXE.
set "CONDA_COMMAND="
if defined CONDA_EXE (
    if exist "%CONDA_EXE%" set "CONDA_COMMAND=%CONDA_EXE%"
)
if defined CONDA_COMMAND goto conda_environment

rem Otherwise, search PATH.
for /f "delims=" %%C in ('where conda.exe 2^>nul') do (
    if not defined CONDA_COMMAND set "CONDA_COMMAND=%%C"
)
if defined CONDA_COMMAND goto conda_environment

rem Common per-user and system-wide Conda installations.
for %%D in (
    "%USERPROFILE%\miniconda3"
    "%USERPROFILE%\anaconda3"
    "%USERPROFILE%\miniforge3"
    "%LOCALAPPDATA%\miniconda3"
    "%LOCALAPPDATA%\anaconda3"
    "%LOCALAPPDATA%\miniforge3"
    "%ProgramData%\miniconda3"
    "%ProgramData%\anaconda3"
    "%ProgramData%\miniforge3"
) do (
    if not defined CONDA_COMMAND (
        if exist "%%~D\Scripts\conda.exe" (
            set "CONDA_COMMAND=%%~D\Scripts\conda.exe"
        )
    )
)
if defined CONDA_COMMAND goto conda_environment

echo ERROR: Could not locate Conda.
echo.
echo Open your Conda-enabled terminal and run:
echo   conda activate %ENV_NAME%
echo   .\run_reezsynth.bat
echo.
echo For a custom Conda installation, set CONDA_EXE to its conda.exe path.
set "RESULT=1"
goto finish

:active_environment
echo [Launcher] Using active environment: %ENV_NAME%
if "%~1"=="" (
    python -X utf8 -u "%DEFAULT_SCRIPT%"
) else (
    python -X utf8 -u %*
)
set "RESULT=%ERRORLEVEL%"
goto finish

:conda_environment
echo [Launcher] Running in Conda environment: %ENV_NAME%
if "%~1"=="" (
    "%CONDA_COMMAND%" run --no-capture-output -n "%ENV_NAME%" python -X utf8 -u "%DEFAULT_SCRIPT%"
) else (
    "%CONDA_COMMAND%" run --no-capture-output -n "%ENV_NAME%" python -X utf8 -u %*
)
set "RESULT=%ERRORLEVEL%"
goto finish

:finish
echo.
if not "%RESULT%"=="0" (
    echo [Launcher] Exited with error code %RESULT%.
    pause
) else (
    rem Keep a double-clicked launcher open so test results remain visible.
    rem When launched from an existing terminal, return immediately.
    echo(%cmdcmdline% | findstr /I /C:" /c " >nul
    if not errorlevel 1 pause
)

popd
endlocal & exit /b %RESULT%