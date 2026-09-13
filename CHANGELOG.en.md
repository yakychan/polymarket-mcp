# Changelog

## 0.2.0 — 2026-09-13

- Classifies known CLOB rejections without turning them into uncertain timeouts.
- Recovers fills when the order endpoint returns 404; deduplicates fills and handles terminal failure and partial confirmation.
- Runs tools outside the async event loop and keeps remote validation outside SQLite write locks.
- Returns MCP `isError`, stable error codes, correlation IDs, and safe diagnostics.
- Adds market/asset exposure limits, maximum open positions, visible budget, and reduce-only mode.
- Adds opt-in persistent local stop-losses, an autonomous monitor, process locking, and `--worker` mode.
- Adds cursor-based audit history, consistent database backups, Chainlink TWAP collection, forecasts, and execution/calibration metrics.
- Adds portable bilingual documentation, examples, regression tests, CI, and allowlisted ZIP distribution.

Processes from 0.1 must be restarted. Existing credentials and histories are preserved. Previous entries do not receive stops automatically.
