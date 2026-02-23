## Steam Deck Steam Input Seed Files

This directory stores repo-managed Steam Input template seeds used by Deck template sync.

Seed files:
- `wii_gc/controller_neptune.vdf`: applied to managed `Wii` and `GC` shortcuts
- `n3ds/controller_neptune.vdf`: applied to managed `N3DS` shortcuts

Current baseline:
- Initial seed snapshot is based on a community `controller_neptune.vdf` template file (`mysmg.vdf`) from EmuDeck community creations.
- This baseline is intended to bootstrap deterministic file seeding and should be replaced with GAMEHUB-owned templates for your runtime expectations.

Refresh workflow:
1. Set the desired template in Steam for one representative GAMEHUB title in each system group (`wii_gc`, `n3ds`).
2. Capture into repo seeds with:
   - `./venv/bin/python scripts/capture_deck_template_seed.py --system wii_gc --title "<Wii or GC title>"`
   - `./venv/bin/python scripts/capture_deck_template_seed.py --system n3ds --title "<N3DS title>"`
3. Commit updated seed files in this folder.

Notes:
- GAMEHUB sync writes per-title template files under Steam's `Steam Controller Configs/<steamid>/config/<normalized_title>/controller_neptune.vdf`.
- Title normalization uses lower-case (`casefold`), replaces `/` and `\` with space, and collapses whitespace.
