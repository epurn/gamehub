# CLI Sync

Command:
```powershell
.\venv\Scripts\python.exe -m gamehub_cli.main sync [flags]
```

## Flags
- `--dry-run`: build and print plan only
- `--verbose`: longer network timeout and extra output context
- `--verify`: re-hash local files before diff decisions
- `--skip-steam`: run sync downloads/state updates but skip Steam lifecycle and Steam file updates
- `--require-steam-closed`: fail if Steam cannot be closed before config writes
- `--config <path>`: TOML config path override

Steam close behavior:
- non-dry sync attempts to close Steam first
- if Steam cannot be closed:
  - with `--require-steam-closed`: sync fails
  - without it: Steam update stage is skipped for safety

## Pipeline order
1. Load config and local state
2. Fetch and validate `/v1/index`
3. Build plan:
   - firmware actions first
   - missing required firmware blocks title sync for that system
   - size mismatch detection for local ROM/assets runs even when `--verify` is off
4. SGDB artwork phase (only when SGDB API key is configured):
   - `--dry-run`: prints planned SGDB lookups/downloads only (no cache writes)
   - real sync: look up titles, fetch configured artwork kinds, cache to local files with safe writes
   - SGDB lookup/download failures emit warnings and do not abort unaffected titles
5. If not `--dry-run`:
   - download firmware then ROM/assets
   - write to `*.part`, verify SHA-256, atomic rename
6. Discover Steam userdata + SteamID
7. Close Steam (best effort), backup configs, run Steam update placeholders, copy cached artwork into Steam grid, reopen Steam
8. Save `state.json`
