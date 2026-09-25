@echo off
setlocal
cd /d %~dp0
set PYTHONUTF8=1

if not exist "%~dp0logs" mkdir "%~dp0logs"
set LOGFILE=%~dp0logs\daily_run.log

echo [%date% %time%] === daily run start === >> "%LOGFILE%"

REM ============================================================
REM 1306ボット(RSI逆張り、trading_agents.py)
REM ============================================================
python fetch_yf.py 1306 10 >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] fetch_yf.py failed, skip 1306 cycle >> "%LOGFILE%"
  goto regime_shift
)

python trading_agents.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] trading_agents.py failed, skip 1306 push >> "%LOGFILE%"
  goto regime_shift
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

:regime_shift
REM ============================================================
REM レジームシフト・ボット(1321/1571デッドクロス、regime_shift_agent.py)
REM 1306ボットとは完全に独立(片方の失敗が他方の実行・pushを止めない設計)
REM ============================================================
python regime_shift_agent.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] regime_shift_agent.py failed, skip regime shift push >> "%LOGFILE%"
  goto end
)

git add state_regime_shift.json >> "%LOGFILE%" 2>&1
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "regime shift daily update %date%" >> "%LOGFILE%" 2>&1
  git push >> "%LOGFILE%" 2>&1
  echo [%date% %time%] pushed state_regime_shift.json >> "%LOGFILE%"
) else (
  echo [%date% %time%] state_regime_shift.json unchanged, skip commit >> "%LOGFILE%"
)

:end
echo [%date% %time%] === daily run end === >> "%LOGFILE%"
endlocal
