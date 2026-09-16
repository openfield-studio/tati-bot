@echo off
setlocal
cd /d %~dp0
set PYTHONUTF8=1

if not exist "%~dp0logs" mkdir "%~dp0logs"
set LOGFILE=%~dp0logs\value_run.log

echo [%date% %time%] === value screener run start === >> "%LOGFILE%"

python value_screener.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] value_screener.py failed, aborting >> "%LOGFILE%"
  exit /b 1
)

python value_performance.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] value_performance.py failed, skip push >> "%LOGFILE%"
  exit /b 1
)

git add value_ranking.json value_history.jsonl value_performance.json >> "%LOGFILE%" 2>&1
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "value screener weekly update %date%" >> "%LOGFILE%" 2>&1
  git push >> "%LOGFILE%" 2>&1
  echo [%date% %time%] pushed value screener data >> "%LOGFILE%"
) else (
  echo [%date% %time%] no change, skip commit >> "%LOGFILE%"
)

echo [%date% %time%] === value screener run end === >> "%LOGFILE%"
endlocal
