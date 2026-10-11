# AutoLedger Local Starter

This is a local-development starter for the AutoLedger DBMS project. It connects to the existing PostgreSQL database `autoledger_db` and provides a basic vehicle search and history page.

## Requirements
- Python 3.10+
- PostgreSQL running locally
- Existing `autoledger_db` database
- VS Code (recommended)

## Windows PowerShell setup
1. Extract this folder and open it in VS Code.
2. In VS Code, open **Terminal → New Terminal**.
3. Create a virtual environment:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
   If `py` is unavailable, try `python -m venv .venv`.
4. From the workspace root, install dependencies into the existing `.venv`:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r .\AutoLedger_Local_Starter\requirements.txt
   ```
5. Keep the workspace-root `.env` file private. If creating it for the first time, copy `AutoLedger_Local_Starter\.env.example` to `.env` and set `DB_PASSWORD` to your PostgreSQL password. The configured PostgreSQL server uses port `2005` on this machine.
6. From the workspace root, run the app:
   ```powershell
   python -m uvicorn backend.main:app --reload --app-dir .\AutoLedger_Local_Starter
   ```
7. Open `http://127.0.0.1:8000` in your browser.
8. API health check: `http://127.0.0.1:8000/api/health`
9. Interactive API docs: `http://127.0.0.1:8000/docs`

## Important
- This starter expects the table/column names created in the AutoLedger schema discussed in the project.
- It is intended for local classroom development, not public production deployment.
- Only use fictional sample data.
- Keep `.env` private; never upload it to GitHub.
