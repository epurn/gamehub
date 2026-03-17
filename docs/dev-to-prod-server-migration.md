# Dev-to-Production Server Migration Checklist

Use this checklist when converting a GAMEHUB server from a development setup into the hardened trusted-LAN production deployment.

Common starting points:
- direct-run `uvicorn` or `python -m gamehub_server.main`
- a Docker Compose dev stack using `latest`
- any setup that currently binds broadly with `0.0.0.0`

## 1) Freeze the dev server state
- Stop new client syncs and managed shortcut sessions from writing to the server during the cutover window.
- Record the current server URL, host, and port.
- Record the current data root and whether the server allows save uploads.
- Record the current runtime shape:
  - direct-run command or service wrapper
  - current image tag if Docker is already in use
  - any non-default index or upload environment variables

## 2) Take a pre-cutover snapshot
- Stop the development server before copying data for the production host.
- Preferred: run the snapshot helper from the deploy bundle or repo root:

```bash
python3 scripts/server_snapshot.py backup --env-file docker/.env --output-dir ./snapshots --apply
```

- The snapshot captures the full server data root plus `docker/.env`, `image-tag.txt`, and `manifest.json`.
- If you are migrating from a non-Compose direct-run setup, still back up the equivalent service/unit files or exported environment values separately.
- Keep the snapshot until the production server passes verification and the first real client sync.

## 3) Validate production data invariants
- Confirm the production data root contains the expected `roms/`, `firmware/`, and optional `saves/` directories.
- Remove or replace any symlinked files or directories anywhere under `roms/`, `firmware/`, or `saves/`.
- If save uploads will be enabled, confirm the target `saves/` tree is writable by Docker on the production host.
- If you are migrating to a new host path, finish copying the full data root before starting the production server.

## 4) Move onto the production deploy artifacts
- Start from the release-matched deploy bundle for the target version.
- Copy `docker/.env.template` to `docker/.env`.
- Set `GAMEHUB_DATA_HOST_PATH` to the production data root.
- Set `GAMEHUB_IMAGE_TAG` to the pinned release tag you intend to run.
- Leave `GAMEHUB_SERVER_BIND_ADDRESS=127.0.0.1` for the first production boot so validation happens before LAN exposure.
- Set `GAMEHUB_MAX_SAVE_UPLOAD_BYTES` only if your rollout policy needs an explicit upload cap.
- Carry forward non-default index settings only when you still want them in production.

Do not carry forward these dev-only habits:
- `GAMEHUB_IMAGE_TAG=latest` for a real server
- `GAMEHUB_SERVER_BIND_ADDRESS=0.0.0.0` unless broad exposure is an explicit choice
- `GAMEHUB_SERVER_LISTEN_HOST` for the Compose deployment

Compose already publishes the container port through `GAMEHUB_SERVER_BIND_ADDRESS`, and the container itself listens on `0.0.0.0` internally.

## 5) Bring up production on loopback first
- Review the rendered config:

```bash
docker compose -f docker/compose.yaml --env-file docker/.env config
```

- Pull the pinned image:

```bash
docker compose -f docker/compose.yaml --env-file docker/.env pull gamehub-server
```

- Start the server:

```bash
docker compose -f docker/compose.yaml --env-file docker/.env up -d
```

- Verify locally before LAN exposure:

```bash
python3 scripts/verify_server_deploy.py --base-url "http://127.0.0.1:8000" --wait-seconds 30
```

- Inspect logs if verification fails:

```bash
docker compose -f docker/compose.yaml --env-file docker/.env logs gamehub-server --tail=200
```

## 6) Cut over to the trusted LAN address
- Choose an explicit host LAN IP if other machines need to reach the server.
- Update `GAMEHUB_SERVER_BIND_ADDRESS` from `127.0.0.1` to that LAN IP.
- Recreate the service so Docker republishes the port:

```bash
docker compose -f docker/compose.yaml --env-file docker/.env up -d
```

- Re-run the verifier against the final LAN URL:

```bash
python3 scripts/verify_server_deploy.py --base-url "http://<SERVER_IP>:8000" --wait-seconds 30
```

- Confirm a second machine on the trusted LAN can reach the server and that unintended interfaces remain closed.

## 7) Retire the dev-only entry point
- Disable any old direct-run service, ad-hoc `uvicorn` command, or legacy compose stack so only the production deployment remains active.
- Record the final pinned image tag, bind address, production host, and backup snapshot location in your rollout notes.
- Keep the pre-cutover snapshot available until the first real client sync and save-upload workflow both behave as expected.
