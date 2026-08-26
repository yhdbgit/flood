# V23 runtime assets

The cached V23 media bundle is intentionally distributed through GitHub
Releases instead of Git. Run `python scripts/setup_v23.py` after cloning, or
set `V23_ASSET_ROOT` to an installed bundle. The installer verifies every file
against `config/runtime_assets_v23.json`.
