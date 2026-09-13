# Version 0.2.0 validation

Performed on 13 September 2026 on Windows with Python 3.13.

- `python -m pytest -q -p no:cacheprovider`: **65 tests passed**.
- `python -m pip check`: no broken requirements.
- `scripts/smoke_public.py`: discovered a live public market and executed an isolated paper trade using real book depth; idempotency was verified.
- `scripts/smoke_feed.py --seconds 15`: received and persisted 30-second and 60-second Chainlink TWAP observations using decimal precision.
- Share archive: allowlisted files, ZIP integrity, bilingual documentation links, and portable JSON/TOML examples were checked.
- The extracted share archive was tested independently: **65 tests passed**.

Coverage includes paper accounting and official settlement, V2 fixture signing, stdio handshake, MCP error results, rejection/timeout recovery, 404 fills, partial and duplicate fills, exposure, concurrency, opt-in stops, restart recovery, autonomous monitoring, pause/reduce-only mode, manual sales, dust, backups, audit filters, safe diagnostics, and archive contents.

No user credentials or operational database were used by the tests. No live money was submitted. Simulated live integration does not replace a recipient's own checks of funds, allowances, wallet signature type, geoblock, and connectivity.
