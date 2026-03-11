@echo off
setlocal
cd /d "%~dp0"

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE=.venv\Scripts\python.exe

echo Building VideoRenamer.exe...
%PYTHON_EXE% -m PyInstaller --noconfirm --clean --onefile --windowed --name VideoRenamer --hidden-import PIL._tkinter_finder --hidden-import google.genai app.py
if errorlevel 1 (
    echo Build failed.
    exit /b %errorlevel%
)

echo Build complete. Output: dist\VideoRenamer.exe
endlocal
