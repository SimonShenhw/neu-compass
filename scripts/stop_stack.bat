@echo off
REM Wrapper so users can double-click or run from cmd without ExecutionPolicy issues.
REM Forwards all args to the .ps1.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_stack.ps1" %*
