@echo off
rem Render the last completed GUI job through the direct CLI in a new output folder.
call "%~dp0run_reezsynth.bat" reezsynth_cli_benchmark.py %*
exit /b %ERRORLEVEL%
