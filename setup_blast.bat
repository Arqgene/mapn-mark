@echo off
setlocal
title BLAST Database Setup Wizard
color 0f

echo ==========================================
echo       BLAST Database Setup
echo ==========================================
echo.
echo This utility helps you create a BLAST database from a reference FASTA file.
echo.

:INPUT
set /p FASTA_FILE="Enter full path to your reference FASTA file (e.g., C:\Data\ref.fasta): "
set FASTA_FILE=%FASTA_FILE:"=%

if not exist "%FASTA_FILE%" (
    echo [ERROR] File not found. Please try again.
    goto INPUT
)

set /p DB_NAME="Enter a name for this database (e.g., my_genome_db): "

echo.
echo [INFO] Processing...
echo 1. Converting path to WSL format...

:: Get dir and filename
for %%I in ("%FASTA_FILE%") do (
    set FILE_DIR=%%~dpI
    set FILE_NAME=%%~nxI
)
set FILE_DIR=%FILE_DIR:~0,-1%

:: Drive letter logic for WSL
set DRIVE=%FILE_DIR:~0,1%
set TAIL=%FILE_DIR:~2%
set TAIL=%TAIL:\=/%
call set WSL_PATH=/mnt/%DRIVE%%TAIL%/%FILE_NAME%
call set WSL_PATH=%%WSL_PATH::=%%
call set WSL_PATH=%%WSL_PATH:C=/c%%
call set WSL_PATH=%%WSL_PATH:D=/d%%
call set WSL_PATH=%%WSL_PATH:E=/e%%

echo    Windows Path: %FASTA_FILE%
echo    WSL Path:     %WSL_PATH%
echo.

echo 2. Running makeblastdb in WSL...
echo.

wsl source ~/.bashrc; conda activate pipeline; makeblastdb -in "%WSL_PATH%" -dbtype nucl -out "%WSL_PATH%.db"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to create BLAST database.
    echo Ensure 'makeblastdb' is installed (run setup.bat first).
    pause
    exit /b
)

echo.
echo [SUCCESS] Database created successfully!
echo Database files are located at:
echo %FASTA_FILE%.db.*
echo.
pause
