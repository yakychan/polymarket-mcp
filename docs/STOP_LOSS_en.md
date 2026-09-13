# Local stop-loss

## Explicit activation

A stop authorizes the monitor to sell without another AI decision when its trigger is met. It never authorizes new buys. The user must request it, and it can be cancelled with `cancel_stop_loss`.

Attach it during execution:

```json
{"quote_id":"QUOTE_ID","reason":"Entry decision","stop_loss_percent":"20","stop_slippage":"0.03"}
```

Or attach it to an existing entry:

```json
{"local_order_id":"ENTRY_ORDER","loss_percent":"20","slippage":"0.03"}
```

```json
{"local_order_id":"ENTRY_ORDER","trigger_price":"0.40","slippage":"0.02"}
```

Choose exactly one trigger. There is one active stop per token and mode. Cancel the old stop before replacing it. A cancellation cannot withdraw a sale that has already been reserved or submitted.

## Price and quantity

`loss_percent` is the percentage fall in the token price from the confirmed average entry, excluding fees. It is not a fall in BTC/ETH or in account equity. `trigger_price` sets an absolute token price between 0 and 1.

The monitor watches the best bid. When it reaches the trigger or lower, the stop latches and remains triggered even if the price recovers. The signed sell limit is `trigger - slippage`, rounded up to the market tick and never below one tick. `slippage` is an absolute price difference per share; `0.03` means three cents.

This is a **local stop-limit on the Up/Down token**, not an exchange-hosted stop. It does not guarantee an exit or a maximum loss. A wide spread can trigger immediately after entry. A price gap below the limit, missing liquidity, FOK rejection, market closure, or a paused monitor can leave shares unsold.

The stop protects only the quantity attributed to its entry. Manual sales are attributed FIFO. Multiple buys of one token remain fungible at the exchange, so this is conservative accounting rather than exchange-level lot isolation. Quantities are rounded down to two decimals and may leave dust below the market minimum.

## States

| State | Meaning |
| --- | --- |
| `armed` | Configured and waiting for the entry or trigger |
| `triggered` | Trigger reached; evaluating or attempting the exit |
| `waiting` | A sale is submitted or uncertain and needs reconciliation |
| `completed` | Authorized quantity sold or the lot was closed manually |
| `cancelled` | Disabled, or the entry never filled |
| `expired` | Operable window ended with quantity remaining |
| `dust` | Remaining amount is below the market minimum |

`last_error`, `attempts`, `quote_id`, and `last_exit_order_id` explain what happened. `completed` does not mean the sale matched the requested loss exactly; inspect fills and fees.

## Restarts and failures

The exit quote is persisted before execution. A crash reuses the same intent. `unknown` and `submitting` orders are never resent under a new ID. The monitor runs inside the MCP process or independently with:

```powershell
.\.venv\Scripts\python.exe -m polymarket_mcp --worker
```

An OS lock allows one monitor per database/mode and another process can take over after exit. The machine must stay awake and connected. Total pause blocks stops; `set_reduce_only(true)` allows exits unless total pause is also active.

`MIN_SECONDS_TO_CLOSE` applies to stops. A stop without a pending sale becomes `expired` near close; a sale already uncertain remains recorded for reconciliation. Winning live positions must be redeemed through Polymarket.
