import vdf
from gamehub_cli.common.config import load_config
from gamehub_cli.sync.steam_stage import resolve_steam_context

ctx = resolve_steam_context(load_config(None))
print("SHORTCUTS_PATH:", ctx.shortcuts_path)

with ctx.shortcuts_path.open("rb") as f:
    data = vdf.binary_load(f)

bad_wrappers = []
bad_gamehub_mismatch = []
managed = 0

for k, e in data.get("shortcuts", {}).items():
    if not isinstance(e, dict):
        continue
    tags = e.get("tags", {})
    vals = [tags[t] for t in sorted(tags, key=lambda x: int(str(x)) if str(x).isdigit() else str(x))] if isinstance(tags, dict) else []
    if "GAMEHUB" not in vals:
        continue
    managed += 1
    exe = str(e.get("Exe", "")).strip().strip('"')
    launch = str(e.get("LaunchOptions", "")).strip()
    has_payload = "shortcut-launch --payload" in launch
    uses_gamehub = "gamehub" in exe.lower()
    uses_python_module = ("python" in exe.lower() and launch.startswith("-m gamehub_cli.main shortcut-launch --payload"))

    if has_payload and not (uses_gamehub or uses_python_module):
        bad_wrappers.append((k, e.get("AppName", ""), exe, launch))
    if uses_gamehub and launch.startswith("-m "):
        bad_gamehub_mismatch.append((k, e.get("AppName", ""), exe, launch))

print("MANAGED_SHORTCUTS:", managed)
print("BAD_WRAPPERS:", len(bad_wrappers))
print("BAD_GAMEHUB_MISMATCH:", len(bad_gamehub_mismatch))
for row in bad_wrappers[:10]:
    print("BAD_WRAPPER:", row)
for row in bad_gamehub_mismatch[:10]:
    print("BAD_GAMEHUB_MISMATCH:", row)