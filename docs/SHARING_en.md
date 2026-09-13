# Sharing and updating

## Build a package

From the repository directory:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/build_share.py
```

This creates `dist/polymarket-mcp-0.2.0.zip` and prints its SHA256. The archive is built from an explicit allowlist: MCP source, tests, scripts, documentation, examples, metadata, and `.env.example`. It excludes `.env`, databases, logs, backups, client settings, virtual environments, old ZIPs, and inherited trading bots.

Share the ZIP and its hash, never the complete work directory. The recipient extracts it, follows [README.en.md](../README.en.md), installs dependencies, and creates a private `.env`. Examples contain placeholder paths and do not configure a wallet automatically.

## Update from 0.1

1. Review pending orders and create a consistent database backup.
2. Stop old MCP and worker processes using that database.
3. Install the new version with `python -m pip install -e ".[dev]"`.
4. Keep the existing `.env`, but review the new market, asset, and position limits.
5. Start a new MCP connection and verify `get_status`, `get_trade_history`, and `list_stop_losses`.

The schema migration is additive. Existing orders remain; previous entries do not receive stops automatically. Uncertain orders remain uncertain until reconciled. Do not run old and new workers against the same database during an upgrade.

## Verification

The local suite uses temporary databases and simulated brokers. Public smoke tests require internet and can fail because of liquidity, market close, service availability, or missing RTDS observations. Live credentials and real orders are not used by the test suite.

To keep stops running after closing the client, run `python -m polymarket_mcp --worker` under a supervisor or persistent terminal. The machine must stay awake and connected. See [VALIDATION_en.md](VALIDATION_en.md) and [STOP_LOSS_en.md](STOP_LOSS_en.md).
