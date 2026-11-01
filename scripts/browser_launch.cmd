@echo off
rem Launch Chrome with remote debugging (CDP) on 127.0.0.1:9222 for OfferLoop apply.
rem Double-click THIS FILE in Windows Explorer. Do NOT click the link inside a web page.
setlocal
set "ROOT=%~dp0..\.."
set "PROFILE=%ROOT%\.local\browser-profile"
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo [ERROR] Chrome not found: %CHROME%
  echo Install Google Chrome, or edit the CHROME path in this file.
  pause
  exit /b 1
)
echo [OK] Chrome : %CHROME%
echo [OK] Profile: %PROFILE%
echo Launching Chrome with remote debugging ...
start "" "%CHROME%" --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check --new-window about:blank
echo [DONE] A new Chrome window should have opened with a fresh profile.
echo [VERIFY] Open http://127.0.0.1:9222/json/version in that window - it should show JSON.
echo [NEXT] Log into https://www.zhaopin.com in that window, then tell the agent you are logged in.
pause
