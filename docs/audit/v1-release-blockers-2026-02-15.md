# V1 Release Blocker List (P0/P1 Only)

## Gate Policy
- Block release on unresolved `P0` and `P1` findings.
- Current date of record: **2026-02-15**.

## Open Blockers
- None.

## Closed Blockers
| Blocker ID | Linked Finding | Closed Date | Closure Evidence |
|---|---|---|---|
| BLK-001 | GH-AUD-001 | 2026-02-15 | `IndexRepository` now serves cached snapshots by default, supports TTL refresh (`GAMEHUB_INDEX_REFRESH_SECONDS`), and manual refresh (`/v1/index?refresh=1`); server API tests cover cached hits + refresh paths. |
| BLK-002 | GH-AUD-002 | 2026-02-15 | `.env.production.template` now uses neutral host-path placeholder/examples, `docker/compose.yaml` no longer hard-pins `linux/amd64`, and compose config validation passes against template values. |

## No Open P0 Items
- No `P0` findings were identified in this audit pass.

## Release Decision Rule
- `BLK-001` and `BLK-002` are now closed; no open `P0`/`P1` blockers remain in this audit set.
