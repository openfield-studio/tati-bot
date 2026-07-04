@echo off
setlocal
cd /d D:\tati
set PYTHONUTF8=1

if not exist "D:\tati\logs" mkdir "D:\tati\logs"
set LOGFILE=D:\tati\logs\daily_run.log

echo [%date% %time%] === daily run start === >> "%LOGFILE%"

python fetch_yf.py 1306 10 >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] fetch_yf.py failed, aborting >> "%LOGFILE%"
  exit /b 1
)

python trading_agents.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] trading_agents.py failed, skip push >> "%LOGFILE%"
  exit /b 1
)

git add state.json >> "%LOGFILE%" 2>&1
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "daily update %date%" >> "%LOGFILE%" 2>&1
  git push >> "%LOGFILE%" 2>&1
  echo [%date% %time%] pushed state.json >> "%LOGFILE%"
) else (
  echo [%date% %time%] state.json unchanged, skip commit >> "%LOGFILE%"
)

echo [%date% %time%] === daily run end === >> "%LOGFILE%"
endlocal
