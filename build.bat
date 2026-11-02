@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] installing pyinstaller ...
python -m pip install --upgrade pyinstaller || goto :err

echo [2/2] building ...
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name AutoClicker ^
    --icon "clicker.ico" ^
    --add-data "clicker.ico;." ^
    autoclicker.py || goto :err

echo.
echo Done: dist\AutoClicker.exe
pause
exit /b 0

:err
echo.
echo Build failed.
pause
exit /b 1
