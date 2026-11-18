@echo off
rem Controllo quotidiano delle versioni delle app TK (attività pianificata TK-controlla-app sul box).
set PYTHONIOENCODING=utf-8
"C:\Program Files\Python313\python.exe" "%~dp0controlla.py" > "%USERPROFILE%\controlla-app.log" 2>&1
