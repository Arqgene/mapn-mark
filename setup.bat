@echo off
setlocal
title BioPipeline Setup Wizard
color 0f

echo ==========================================
echo       BioPipeline System Setup
echo ==========================================
echo.

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.12+ and try again.
    pause
    exit /b
)

:: 2. Install Windows Dependencies (Flask Server)
echo [1/3] Installing Windows Server Dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install pip requirements.
    pause
    exit /b
)
echo [OK] Dependencies installed.
echo.

:: 3. Initialize Database
echo [2/3] Initializing Database...
echo This will create the database and tables if they don't exist.
echo You may see a prompts if creating a user interactively.
echo.
python create_user.py
echo.

:: 4. Setup WSL Environment
echo [3/3] Setting up WSL Environment (Bioinformatics Tools)...
echo This will run 'install.sh' inside your default WSL distribution.
echo.

wsl --status >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] WSL is not detected. Please install WSL 2 and Ubuntu.
    pause
    exit /b
)

:: Convert current path to WSL path
:: (Simple approximation: D:\gene -> /mnt/d/gene)
:: But checking if we are in the right folder is enough usually
wsl bash install.sh

if %errorlevel% neq 0 (
    echo [ERROR] WSL setup failed. Please check the logs above.
    pause
    exit /b
)

echo.
echo ==========================================
echo      Setup Completed Successfully!
echo ==========================================
echo.
echo You can now start the application using 'start.bat'
echo.
pause
