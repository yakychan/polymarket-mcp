# Database and audit history

The default local database is `data/trading.sqlite3`, using SQLite WAL and `synchronous=FULL`. Startup adds tables and indexes without deleting the 0.1 history. Paper and live records share the file but are filtered by mode.

| Table | Contents |
| --- | --- |
| `state` | Paper balances, pause/reduce-only flags, live wallet, heartbeat |
| `quotes` | Persistent quote intents |
| `orders` | Latest accumulated state for each order; unique `quote_id` |
| `positions` | Paper inventory, cost, and settlements |
| `events` | Ordered audit stream for orders, fills, stops, pauses, and forecasts |
| `stops` | Stop configuration, state, linked entry/exit, and errors |
| `observations` | Chainlink TWAP symbol, window, source/receive times, decimal value |
| `forecasts` | Pre-close probabilities and reasons |
| `resolutions` | Official winner per condition |
| `snapshots` | Top bid/ask, timestamps, and fees at snapshot time |
| `tool_calls` | Tool duration, error code, and safe diagnostic by correlation ID |

Use `get_trade_history` for accumulated order state, `get_movements` for cursor-based audit without external calls, `poll_updates` for synchronization plus events, `list_stop_losses` for stops, and `get_metrics` for performance and calibration. Keep separate cursors for different filters. An event is not another debit; `execution` is accumulated by order ID.

Amounts are stored as decimal strings. Do not use floating-point conversion for accounting. Chainlink `observed` belongs to the source clock; `received` and events use the local clock. Market validations use a calibrated CLOB clock.

## Consistent backup

```powershell
.\.venv\Scripts\python.exe scripts/backup_db.py --source data/trading.sqlite3 --output backups/trading-copy.sqlite3
```

The script uses SQLite's backup API, includes WAL data, checks integrity, and refuses to overwrite an existing destination. Stop all MCP and worker processes before restoring. A restored live copy can omit later exchange activity; reconcile before resuming orders. Do not delete order, fill, or active-stop rows to reclaim space because they are part of idempotency and exposure controls.

## Read-only SQL examples

```sql
SELECT id, datetime(created, 'unixepoch') AS utc,
       json_extract(body, '$.market.slug') AS market,
       json_extract(body, '$.status') AS status
FROM orders WHERE mode = 'paper' ORDER BY created DESC LIMIT 100;

SELECT seq, datetime(created, 'unixepoch') AS utc, kind, body
FROM events WHERE mode = 'paper' ORDER BY seq LIMIT 100;

SELECT id, status, json_extract(body, '$.last_error') AS last_error
FROM stops WHERE mode = 'paper';
```
