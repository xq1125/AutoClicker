@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Python not found. Please install Python 3 first
    echo  and check "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)
start "" pythonw "%~dp0autoclicker.py"
