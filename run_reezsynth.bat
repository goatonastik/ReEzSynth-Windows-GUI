@echo off
setlocal
chcp 65001 >nul
title ReEzSynth Windows GUI

rem Always use the project folder as the working directory.
pushd "%~dp0"
if errorlevel 1 (
    echo ERROR: Could not open the project folder.
    pause
    exit /b 1
)

set "ENV_NAME=reezsynth"
if exist ".reezsynth-env-name.txt" set /p "ENV_NAME="<".reezsynth-env-name.txt"
if defined REEZSYNTH_ENV set "ENV_NAME=%REEZSYNTH_ENV%"
set "DEFAULT_SCRIPT=reezsynth_gui.py"
set "RESULT=0"
set "CONDA_COMMAND="

rem No arguments: start the consolidated GUI.
rem With arguments: run the specified script and forward its arguments.
if "%~1"=="" (
    if not exist "%DEFAULT_SCRIPT%" (
        echo ERROR: GUI file not found:
        echo   %DEFAULT_SCRIPT%
        echo.
        echo Place this launcher beside reezsynth_gui.py.
        set "RESULT=1"
        goto finish
    )
) else (
    if not exist "%~1" (
        echo ERROR: Script not found:
        echo   %~1
        echo.
        echo Examples:
        echo   run_reezsynth.bat
        echo   run_reezsynth.bat test_reezsynth_worker.py
        set "RESULT=1"
        goto finish
    )
)

rem Prefer the environment that is already active.
if /I "%CONDA_DEFAULT_ENV%"=="%ENV_NAME%" if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" goto active_environment

rem Conda normally provides this variable in initialized terminals.
rem A fresh setup records its installation path for Explorer/double-click launches.
if exist ".reezsynth-conda-path.txt" set /p "CONDA_COMMAND="<".reezsynth-conda-path.txt"
if defined CONDA_COMMAND if not exist "%CONDA_COMMAND%" set "CONDA_COMMAND="
if defined CONDA_COMMAND goto conda_environment

if defined CONDA_EXE (
    if exist "%CONDA_EXE%" set "CONDA_COMMAND=%CONDA_EXE%"
)
if defined CONDA_COMMAND goto conda_environment

rem Search PATH.
for /f "delims=" %%C in ('where conda.exe 2^>nul') do (
    if not defined CONDA_COMMAND set "CONDA_COMMAND=%%C"
)
if defined CONDA_COMMAND goto conda_environment

rem Search common Conda installation locations.
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
echo For a custom installation, set CONDA_EXE to its conda.exe path.
echo For first-time setup, see INSTALL_WINDOWS.md and setup_reezsynth.ps1.
set "RESULT=1"
goto finish

:active_environment
echo [Launcher] Using active environment: %ENV_NAME%

if "%~1"=="" (
    "%CONDA_PREFIX%\python.exe" -X utf8 -u "%DEFAULT_SCRIPT%"
) else (
    "%CONDA_PREFIX%\python.exe" -X utf8 -u %*
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
if not "%RESULT%"=="0" (
    echo.
    echo [Launcher] Exited with error code %RESULT%.
    pause
)

popd
endlocal & exit /b %RESULT%
