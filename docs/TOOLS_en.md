# MCP tool reference · 0.2

There are 21 tools. Successful responses contain `ok`, `mode`, `data`, and `correlation_id`. Failures return MCP `isError=true` plus `ok=false`, `error`, `code`, `retryable`, and `correlation_id`. A retryable read or validation error never authorizes resending an uncertain order with a new quote.

| Tool | Main parameters | Effect |
| --- | --- | --- |
| `get_status` | — | Limits, exposure, budget, pause, and monitor heartbeat |
| `discover_markets` | `asset?`, `windows=3` (1..6) | Reads current and upcoming markets |
| `get_market_snapshot` | `slug` | Reads rules/books/fees and stores a summary |
| `quote_trade` | `slug`, `outcome`, `side`, `amount`, `limit_price` | Stores a quote; does not submit |
| `execute_trade` | `quote_id`, `reason`, `stop_loss_percent?`, `stop_slippage="0.03"` | Executes and can authorize a stop-loss |
| `get_portfolio` | — | Balance and positions for the active mode |
| `get_trade_history` | `limit=50` (1..200), `offset=0` | Persisted orders |
| `settle_paper` | — | Credits paper settlements using the official winner |
| `sync_orders` | — | Live reconciliation or paper settlement |
| `poll_updates` | `after=0`, `limit=100` (1..200) | Synchronizes and returns events |
| `cancel_order` | `local_order_id` | Attempts a live cancel; never reverses fills |
| `set_trading_paused` | `paused` | Persistent total pause, including stops |
| `set_reduce_only` | `enabled` | Blocks buys and allows exits |
| `set_stop_loss` | `local_order_id`, `loss_percent?`, `trigger_price?`, `slippage="0.03"` | Authorizes one stop trigger |
| `list_stop_losses` | `active_only=false`, `limit=100`, `offset=0` | Lists active or historical stops |
| `cancel_stop_loss` | `stop_id` | Disables future stop submissions |
| `get_movements` | `after=0`, `limit=100`, `kind?`, `slug?` | Local cursor-based audit; no sync |
| `get_market_context` | `slug` | Rules and persisted 30/60s TWAP references |
| `get_price_history` | `asset`, `window=30`, `since?`, `limit=500` | Locally received TWAP observations |
| `record_forecast` | `slug`, `outcome`, `probability`, `reason` | Stores a pre-close probability |
| `get_metrics` | — | Execution, latency, errors, and calibration |

Trading decimals and probabilities are strings. `since` is a Unix UTC timestamp in seconds. Assets are `btc`, `eth`, `sol`, and `xrp`; outcomes are `up` and `down`; sides are `BUY` and `SELL`.

## Recovery codes

| Code | Action |
| --- | --- |
| `QUOTE_NOT_FOUND` | Check the ID, mode, and database |
| `QUOTE_EXPIRED`, `QUOTE_CHANGED` | Quote again if no submission occurred |
| `INSUFFICIENT_LIQUIDITY`, `STALE_BOOK` | Wait for data/liquidity and retry the read |
| `ORDER_UNKNOWN` | Reconcile; do not create another intent for that send |
| `ORDER_PENDING` | Wait for the pending sale to finish |
| `BET_LIMIT`, `DAILY_LIMIT` | Reduce the amount or wait |
| `MARKET_EXPOSURE_LIMIT`, `ASSET_EXPOSURE_LIMIT`, `POSITION_LIMIT` | Review exposure |
| `TRADING_PAUSED`, `REDUCE_ONLY` | Respect the active mode |
| `STOP_EXISTS` | Inspect the current stop before replacing it |
| `INVENTORY_CHANGED` | Recalculate the exit amount |
| `PUBLIC_API_ERROR` | Retry only when `retryable` is true |
| `INTERNAL_ERROR` | Search diagnostics by `correlation_id` |

An order can be returned with `ok=true` and `data.status="rejected"` or `"unknown"`; inspect the order status, not just `ok`. Events from one order are not additional debits.
