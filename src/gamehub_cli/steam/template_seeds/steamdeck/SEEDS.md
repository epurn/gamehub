## Steam Deck Steam Input Seed Files

This directory stores repo-managed Steam Input template seeds used by Deck template sync.

Seed files:
- `wii_gc/wii_0.vdf`: applied to managed `Wii` shortcuts
- `n3ds/3ds_0.vdf`: applied to managed `N3DS` shortcuts

Current baseline:
- Initial seed snapshot is based on a community Deck template file (`mysmg.vdf`) from EmuDeck community creations.
- Stage 2 policy:
  - committed seed files are authoritative payloads
  - GAMEHUB writes raw seed bytes with no runtime metadata rewrite
  - manual seed edits are preserved in output as-is

Why these seed files are still required:
- They are the committed deterministic source of full Steam Input mapping graphs for managed `Wii`/`N3DS`.
- Runtime template generation depends on these payloads directly.
- Removing seeds would prevent GAMEHUB from reconstructing managed Deck templates during sync.

Refresh workflow:
1. Set the desired template in Steam for one representative GAMEHUB title in each system group (`wii_gc`, `n3ds`).
2. Capture into repo seeds with:
   - Windows: `.\venv\Scripts\python.exe scripts/capture_deck_template_seed.py --system wii_gc --title "<Wii or GC title>"`
   - Windows: `.\venv\Scripts\python.exe scripts/capture_deck_template_seed.py --system n3ds --title "<N3DS title>"`
   - Linux/macOS: `./venv/bin/python scripts/capture_deck_template_seed.py --system wii_gc --title "<Wii or GC title>"`
   - Linux/macOS: `./venv/bin/python scripts/capture_deck_template_seed.py --system n3ds --title "<N3DS title>"`
3. Commit updated seed files in this folder.

Notes:
- GAMEHUB sync writes per-title template files under:
  - `Steam Controller Configs/<steamid>/config/<normalized_title>/gamehub_wii.vdf` (`Wii`)
  - `Steam Controller Configs/<steamid>/config/<normalized_title>/gamehub_3ds.vdf` (`N3DS`)
  - when a title contains apostrophes, an apostrophe-safe alias directory is also written with the same `gamehub_*.vdf` payload
- GAMEHUB sync also updates `Steam Controller Configs/<steamid>/config/configset_controller_neptune.vdf`:
  - `controller_config` normalized title keys and companion alias keys (`appid`/signed/title variants) are set to `template=CLOUD_<normalized_title>/gamehub_wii` (`Wii`) or `template=CLOUD_<normalized_title>/gamehub_3ds` (`N3DS`)
- GAMEHUB also mirrors those `controller_config` selections to active `configset_*.vdf` files (including `configset_controller_*.vdf` variants).
- When present, GAMEHUB mirrors per-title/template-configset writes into `userdata/<steamid>/241100/remote/*/config/` so Deck startup local+cloud input roots stay aligned.
- Managed sync force-overwrites per-title selection aliases in configsets but does not remove legacy title-level template variant files.
- Title normalization uses lower-case (`casefold`), replaces `/` and `\` with space, and collapses whitespace.
- Apostrophe-safe aliasing converts `'`/`’` to spaces and re-collapses whitespace.
