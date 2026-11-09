@echo off
setlocal
cd /d "%~dp0"
python pinterest_downloader.py %*
endlocal
