# Development

## Environment
- Python: 3.12+
- Required local virtual environment: `venv/`

## First-time setup (Windows PowerShell)
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
.\venv\Scripts\pip.exe install -e .[dev]
```

## Run server
```powershell
.\venv\Scripts\python.exe -m uvicorn gamehub_server.main:app --host 0.0.0.0 --port 8000
```

## Run CLI
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main sync --dry-run
```

## Run tests
```powershell
.\venv\Scripts\python.exe -m pytest -q
```
