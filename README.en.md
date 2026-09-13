# Polymarket MCP · 5-minute Up/Down

Spanish version: [README.md](README.md). The English guides are next to the Spanish guides with the `_en.md` suffix.

Local Python MCP server for discovering BTC/ETH/SOL/XRP five-minute markets, paper or live trading, and persistent SQLite accounting. The client AI chooses entries. A separate monitor executes only stop-losses explicitly requested by the user.

Version **0.2.0**. Transport **stdio**. Requires Python 3.11+. No AI-provider key is needed. Each user supplies their own wallet credentials and database; the distributable archive contains no credentials.

## Quick installation

Windows / PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m polymarket_mcp --check
```

Linux / macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp -n .env.example .env
.venv/bin/python -m pytest -q
.venv/bin/python -m polymarket_mcp --check
```

The example starts in `paper` mode with a virtual USD 1,000 balance and real public market data. `--check` only validates configuration and reads public APIs; it does not sign or submit orders. Use an absolute `POLYMARKET_ENV_FILE` when launching from another directory.

## Connect an MCP client

Launch the virtual-environment Python with `run_mcp.py`, using absolute paths. Restart the connection after changing `.env`.

```json
{
  "mcpServers": {
    "polymarket": {
      "command": "C:/path/polymarket-mcp/.venv/Scripts/python.exe",
      "args": ["C:/path/polymarket-mcp/run_mcp.py"],
      "env": {"POLYMARKET_ENV_FILE": "C:/path/polymarket-mcp/.env"}
    }
  }
}
```

For Codex, merge [examples/codex.toml](examples/codex.toml) into the client configuration, or register it with:

```powershell
codex mcp add polymarket --env "POLYMARKET_ENV_FILE=C:/path/polymarket-mcp/.env" -- "C:/path/polymarket-mcp/.venv/Scripts/python.exe" "C:/path/polymarket-mcp/run_mcp.py"
```

Codex supports the `command`, `args`, `env`, `startup_timeout_sec`, and `tool_timeout_sec` fields used in the example. See the [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). Do not put wallet keys in client configuration files that you share.

## First session

Suggested request:

> Check the mode, balance, limits, and monitor health. Analyze five-minute BTC Up/Down markets using the rules, order book, and available Chainlink data. Record your estimated probability. Before trading, show the estimate, quote, and reason. If I ask for a stop-loss, configure it and explain its minimum exit price. Report all movements with their actual status.

Normal flow: `get_status` → `get_portfolio` → `discover_markets` → `get_market_snapshot` / `get_market_context` → `record_forecast` → `quote_trade` → `execute_trade` → `poll_updates`.

`BUY amount` is USD notional plus fees. `SELL amount` is shares. Amounts support up to two decimals and prices must follow the market tick. Orders are FOK: they must fill completely within the limit or be rejected.

To attach a stop-loss while executing:

```json
{"quote_id":"ID_FROM_QUOTE","reason":"Entry decision","stop_loss_percent":"20","stop_slippage":"0.03"}
```

The entry and stop configuration are stored atomically. In live mode the monitor waits for entry confirmation before calculating the trigger. Reusing a `quote_id` returns the same order and never creates another entry.

## Automatic stop-loss

Use `set_stop_loss` for an existing entry, or pass `stop_loss_percent` to `execute_trade`. A stop is never created merely by starting the server. A 20% stop on a 0.50 average entry triggers when the token bid reaches 0.40 or less. `slippage=0.03` permits a minimum signed sell price of 0.37, rounded to the market tick.

This is a **local stop-limit on the Up/Down token**, not on BTC/ETH and not an exchange-hosted stop. It does not guarantee an exit or a maximum loss. If liquidity is insufficient, the monitor records the failure and retries while the market remains tradable. An uncertain submission is reconciled and never resent with a new intent.

The monitor runs inside the MCP process. To keep it alive after closing the client, run:

```powershell
.\.venv\Scripts\python.exe -m polymarket_mcp --worker
```

Use the same `.env`, mode, and `DATABASE_PATH`. An OS lock allows one monitor per database/mode; another process can take over after the first exits. `get_status.monitor` reports heartbeat and health, and `list_stop_losses` reports each stop's errors. Full behavior is documented in [STOP_LOSS_en.md](docs/STOP_LOSS_en.md).

Total pause blocks purchases, sales, and stops. `set_reduce_only(true)` blocks purchases while allowing exits unless total pause is also enabled.

## History and database

By default, everything is stored in `data/trading.sqlite3`: quotes, orders, events, paper positions, stops, forecasts, official resolutions, Chainlink observations, snapshots, and diagnostics. Restarting does not erase history or reset an existing paper balance.

Use `get_trade_history` for accumulated order state, `get_movements` for cursor-based audit history, and `get_metrics` for latency, errors, price differences, and forecast evaluation. `poll_updates` synchronizes before returning events. Events from one order are not additional debits.

Create a consistent backup, including WAL data:

```powershell
.\.venv\Scripts\python.exe scripts/backup_db.py --source data/trading.sqlite3 --output backups/trading-copy.sqlite3
```

See [DATABASE_en.md](docs/DATABASE_en.md) for schema and restoration guidance.

## Configuration

`.env` overrides inherited environment variables. Changes require restarting every process using that configuration. The important limits are `MAX_BET_USD`, `MAX_DAILY_SPEND_USD`, `MAX_MARKET_EXPOSURE_USD`, `MAX_ASSET_EXPOSURE_USD`, `MAX_OPEN_POSITIONS`, `QUOTE_TTL_SECONDS`, `MIN_SECONDS_TO_CLOSE`, `MAX_BOOK_AGE_SECONDS`, `MONITOR_INTERVAL_SECONDS`, and `ENABLE_CHAINLINK_FEED`. The complete table is in `.env.example` and [TOOLS_en.md](docs/TOOLS_en.md).

Live mode requires the CLOB credentials and wallet settings described in `.env.example`. This MCP does not create approvals, transfer funds, or redeem winning positions. It checks geoblock before submitting.

## Tests and sharing

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/smoke_public.py
.\.venv\Scripts\python.exe scripts/smoke_feed.py --seconds 15
.\.venv\Scripts\python.exe scripts/build_share.py
```

`build_share.py` creates an allowlisted ZIP and excludes `.env`, databases, backups, private client settings, virtual environments, and inherited bots. Share the ZIP, not the entire work directory. See [SHARING_en.md](docs/SHARING_en.md), [ARCHITECTURE_en.md](docs/ARCHITECTURE_en.md), and [VALIDATION_en.md](docs/VALIDATION_en.md).

Known limits: paper results do not model all live latency and liquidity competition; RTDS has no replay; live fees may be unknown per fill; live positions are limited by the Data API response; and the monitor requires an awake, connected process. Refer to the linked guides for recovery details.

[![TEST LOCAL](https://img.youtube.com/vi/TkdXEhvAggg/0.jpg)](https://www.youtube.com/watch?v=TkdXEhvAggg)
