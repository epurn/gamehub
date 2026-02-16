# Release vX.Y.Z

## Highlights
- 

## Server
- Docker image: `ghcr.io/<org>/gamehub-server:vX.Y.Z`
- Deploy bundle zip: `gamehub-server-deploy-vX.Y.Z.zip`
- Deployment notes:
  - Pull: `docker pull ghcr.io/<org>/gamehub-server:vX.Y.Z`
  - Run with compose: set `GAMEHUB_SERVER_IMAGE=ghcr.io/<org>/gamehub-server` and `GAMEHUB_IMAGE_TAG=vX.Y.Z` in `.env.production`, then run `docker compose -f docker/compose.yaml --env-file .env.production up -d`

## Client
- Linux wheel:
  - `gamehub-<version>-py3-none-any.whl`
- Windows EXE:
  - `gamehub-windows-amd64.exe`

## Compatibility / Migration Notes
- 

## Known Limitations
- 

## Checksums
- See `checksums.txt` in release assets.
