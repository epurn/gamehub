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

## EPIC-001 smoke test (server index + file serving)
Use the fixture library to validate end-to-end API behavior quickly.

```powershell
$env:GAMEHUB_DATA_DIR = (Resolve-Path 'tests/fixtures/indexer_case').Path
.\venv\Scripts\python.exe -m uvicorn gamehub_server.main:app --host 127.0.0.1 --port 8011
```

In another PowerShell:

```powershell
.\venv\Scripts\python.exe -c "import httpx; r=httpx.get('http://127.0.0.1:8011/v1/index', timeout=5.0); print(r.status_code); print(r.json()['index_version']); print(len(r.json()['titles']))"
```

Expected output:
- `200`
- `1` (index version)
- `1` (fixture title count)

Fixture layout reminder:
- `roms/<system>/<title.ext>`
- `firmware/<system>/<filename>`
