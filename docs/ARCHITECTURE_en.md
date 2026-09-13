# Architecture and recovery

```text
MCP client ──stdio── server.py ──threads── Engine
                                      ├── PublicAPI: Gamma/CLOB/Data
                                      ├── LiveBroker: signing/submission/reconciliation
                                      └── Store: SQLite + audit history
Monitor (one DB/mode owner) ── Stops ── Engine.execute
                         └── maintenance: sync/resolutions
RTDS collector ── observations
Insights ── market context, forecasts, and metrics
```

Tool functions run through `anyio.to_thread.run_sync`, so slow network calls do not block the MCP event loop. Read transactions use `BEGIN`; reservations and intent writes use short `BEGIN IMMEDIATE` transactions. Remote validation and signing happen outside the write lock.

Execution flow:

1. Read the quote or return the existing receipt for its `quote_id`.
2. Re-read market identity, fees, book, balance, and geoblock, then prepare the signature.
3. Re-check idempotency, pause, exposure, freshness, and expiry in a short transaction. Persist the order hash and any requested stop.
4. Commit, then POST to the exchange.
5. Persist the response or uncertainty without overwriting a newer reconciliation.

A crash between persistence and POST can leave `submitting`. It is kept for investigation and never resent with another ID. A client timeout does not prove that the exchange did not accept the order.

Reconciliation checks order and trade identity, searches trades even when the order endpoint returns 404, deduplicates fill IDs, and preserves known confirmations. Only `CONFIRMED` quantities become execution. Complete all-confirmed coverage becomes `confirmed`; all-failed coverage becomes `failed`; a terminal mixture becomes `partially_confirmed`; incomplete coverage remains pending or uncertain.

The monitor evaluates stops separately from slow synchronization work. OS file locking prevents two workers from submitting the same stop. RTDS reconnects with a heartbeat and stores exact E18 Chainlink values. It has no replay, so missing observations remain missing.

Live fees can be unavailable per fill, winning positions are redeemed through Polymarket, and all limits cover only activity recorded by this database. There is no public HTTP endpoint, arbitrary SQL tool, approval transaction, transfer, or automatic redeem.
