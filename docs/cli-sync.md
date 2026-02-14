# CLI Sync

Command:
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main sync [flags]
```

## Flags
- `--dry-run`: build and print plan only
- `--verbose`: longer network timeout and extra output context
- `--verify`: re-hash local files before diff decisions
- `--require-steam-closed`: fail if Steam cannot be closed before config writes
- `--config <path>`: TOML config path override

## Pipeline order
1. Load config and local state
2. Fetch and validate `/v1/index`
3. Build plan:
   - firmware actions first
   - missing required firmware blocks title sync for that system
4. If not `--dry-run`:
   - download firmware then ROM/assets
   - write to `*.part`, verify SHA-256, atomic rename
5. Discover Steam userdata + SteamID
6. Close Steam (best effort), backup configs, run Steam update placeholders, reopen Steam
7. Save `state.json`
