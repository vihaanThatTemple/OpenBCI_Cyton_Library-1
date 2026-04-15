@echo off
REM Build CytonRecorder.exe with PyInstaller.
REM Requires: pip install -r requirements-dev.txt
REM
REM Run from this directory:  build.bat
REM Output:                    dist\CytonRecorder.exe

pyinstaller --onefile --windowed --icon=icon.ico --name=CytonRecorder cyton_recorder.py
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)
echo.
echo Build complete: dist\CytonRecorder.exe
