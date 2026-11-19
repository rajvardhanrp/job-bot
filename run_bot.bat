@echo off
cd /d "%~dp0"
title Job Bot
echo ==============================
echo           JOB BOT
echo ==============================
echo.

where py >nul 2>nul
if errorlevel 1 goto nopython

echo Setting up, please wait...
py -m pip install -q pypdf python-docx

set RES=
if exist resume.pdf set RES=resume.pdf
if exist resume.docx set RES=resume.docx
if exist resume.txt set RES=resume.txt
if "%RES%"=="" goto noresume

echo.
set CITIES=
set /p CITIES=Type your cities with commas and press Enter [default Pune,Kolhapur,Bangalore]: 
if "%CITIES%"=="" set CITIES=Pune,Kolhapur,Bangalore

set REM=
set /p REM=Include remote jobs? Press Enter for yes, or type N for no: 
set FLAG=--remote
if /i "%REM%"=="N" set FLAG=

echo.
echo Finding jobs, this takes about a minute...
py job_bot.py --resume "%RES%" --locations "%CITIES%" %FLAG%
if errorlevel 1 goto failed

start "" jobs.html
echo.
echo Done. Your jobs page is open in the browser.
pause
exit /b

:nopython
echo Python is not installed.
echo Install it from python.org and tick "Add Python to PATH", then double-click this file again.
pause
exit /b

:noresume
echo No resume found.
echo Put your resume in this same folder and name it resume.pdf or resume.docx, then double-click this file again.
pause
exit /b

:failed
echo Something went wrong. Take a screenshot of this window and send it to Claude.
pause
exit /b