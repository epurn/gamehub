# Release Process

## Versioning
- Use semantic versioning (`MAJOR.MINOR.PATCH`).
- Tag format: `vX.Y.Z`.

## Release Checklist
1. Ensure tests pass:
```powershell
.\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```
2. Bump version in `pyproject.toml`.
3. Update release notes/changelog.
4. Create and push tag:
```powershell
git tag vX.Y.Z
git push origin vX.Y.Z
```
5. Verify GitHub Actions:
   - server image release workflow
   - client artifact release workflow
6. Validate artifacts:
   - server image on GHCR
   - Linux wheel on GitHub Release
   - Windows EXE on GitHub Release
   - checksums file
7. Run post-release smoke checks:
   - deploy server and run `scripts/verify_server_deploy.ps1`
   - run client `--help` and `sync --dry-run`

## Artifact Naming
- Server image: `ghcr.io/<org>/gamehub-server:vX.Y.Z`
- Linux wheel: `gamehub-<version>-py3-none-any.whl`
- Windows executable: `gamehub-windows-amd64.exe`
- Checksums: `checksums.txt`

## Known Scope Limits (Current Phase)
- Architecture: `amd64` only
- Deployment: LAN-only/no auth
