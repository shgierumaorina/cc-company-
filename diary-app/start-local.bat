@echo off
rem diary-app local launcher (Windows)
rem Without TURSO_DATABASE_URL in .env.local, data is saved to data\diary.db
cd /d "%~dp0"

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js not found. Install Node.js 20.9 or later: https://nodejs.org/
  pause
  exit /b 1
)

if not exist node_modules (
  call npm ci || goto :fail
)

call npm run build || goto :fail

start "" http://localhost:3000
call npm start
exit /b 0

:fail
echo Failed. See the error above.
pause
exit /b 1
