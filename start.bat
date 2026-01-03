@echo off
echo Starting BioPipeline in PRODUCTION mode...
set FLASK_ENV=production
python main.py
pause
