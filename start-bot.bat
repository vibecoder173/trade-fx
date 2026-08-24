@echo off
REM ===================================================
REM  Double-click this file to start your trading bot.
REM  A window will open and stay running - leave it open.
REM  To stop the bot: click the window and press Ctrl+C,
REM  or just close the window.
REM ===================================================
cd /d "%~dp0"
echo Starting Crypto Trade Assistant bot...
python bot.py
echo.
echo The bot has stopped. You can close this window.
pause
