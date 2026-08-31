@echo off
rem run_claudiu.bat - double-click launcher
rem "py" must resolve to the Python interpreter where claudiu is
rem installed (pip install -e .). If it does not, edit this file to call
rem that interpreter directly, e.g. "python -m claudiu %*" or the full
rem path to python.exe.
py -m claudiu %*
if errorlevel 1 pause
