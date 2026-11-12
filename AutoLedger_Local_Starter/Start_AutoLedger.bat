
@echo off
cd /d "C:\Users\rabia tabbassam\Desktop\Auto_legder\AutoLedger_Local_Starter"
call .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
pause
