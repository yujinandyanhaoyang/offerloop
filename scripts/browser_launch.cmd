@echo off
rem Launch Chrome with remote debugging for the job-apply CDP channel.
rem Run this on the host (not inside the DSH sandbox). Log into BOSS once in the new window.
setlocal
set "ROOT=%~dp0..\.."
set "PROFILE=%ROOT%\.local\browser-profile"
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo Chrome not found: %CHROME%
  pause
  exit /b 1
)
start "" "%CHROME%" --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check
echo Chrome launched. CDP: http://127.0.0.1:9222
echo Profile: %PROFILE%
echo Log into BOSS once in the new window; login will persist for next runs.
pause
