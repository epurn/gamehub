## Steam Deck Steam Input Seed Files

This directory stores repo-managed Steam Input template seeds used by Deck template sync.

Seed files:
- `wii_gc/wii_0.vdf`: applied to managed `Wii` and `GC` shortcuts
- `n3ds/3ds_0.vdf`: applied to managed `N3DS` shortcuts

Current baseline:
- Initial seed snapshot is based on a community Deck template file (`mysmg.vdf`) from EmuDeck community creations.
- This baseline is intended to bootstrap deterministic file seeding and should be replaced with GAMEHUB-owned templates for your runtime expectations.

Refresh workflow:
1. Set the desired template in Steam for one representative GAMEHUB title in each system group (`wii_gc`, `n3ds`).
2. Capture into repo seeds with:
   - `./venv/bin/python scripts/capture_deck_template_seed.py --system wii_gc --title "<Wii or GC title>"`
   - `./venv/bin/python scripts/capture_deck_template_seed.py --system n3ds --title "<N3DS title>"`
3. Commit updated seed files in this folder.

Notes:
- GAMEHUB sync writes per-title template files under:
  - `Steam Controller Configs/<steamid>/config/<normalized_title>/wii_0.vdf` (`Wii`/`GC`)
  - `Steam Controller Configs/<steamid>/config/<normalized_title>/3ds_0.vdf` (`N3DS`)
- GAMEHUB sync also updates `Steam Controller Configs/<steamid>/config/configset_controller_neptune.vdf`:
  - `controller_config` managed entries are set to `template=wii_0` (`Wii`/`GC`) or `template=3ds_0` (`N3DS`) with `autosave=1`
- GAMEHUB also mirrors those `controller_config` selections to active `configset_*.vdf` files (excluding other `configset_controller_*.vdf` variants).
- Title normalization uses lower-case (`casefold`), replaces `/` and `\` with space, and collapses whitespace.
