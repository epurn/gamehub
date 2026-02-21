$ErrorActionPreference = "Stop"

pyinstaller --noconfirm --clean --onefile --name gamehub-windows-amd64 --paths . --paths src packaging/windows/entrypoint.py

Write-Host "Built dist/gamehub-windows-amd64.exe"
