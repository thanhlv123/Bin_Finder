@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_bin_finder.py
) else (
  py -3.12 run_bin_finder.py
)
endlocal
