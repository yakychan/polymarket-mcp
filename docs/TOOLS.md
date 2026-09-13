# Referencia MCP 0.2

Hay 21 herramientas. Éxitos: `ok`, `mode`, `data`, `correlation_id`. Fallos: `isError=true` en el resultado MCP y campos `ok=false`, `error`, `code`, `retryable`, `correlation_id`. `retryable` se refiere a fallos de consulta/validación; nunca autoriza repetir un envío incierto con otra cotización.

| Herramienta | Parámetros principales | Efectos |
| --- | --- | --- |
| `get_status` | — | Límites, exposición, presupuesto, pausa y heartbeat |
| `discover_markets` | `asset?`, `windows=3` (1..6) | Consulta mercados actuales/próximos |
| `get_market_snapshot` | `slug` | Lee libros/reglas/fees y guarda resumen |
| `quote_trade` | `slug`, `outcome`, `side`, `amount`, `limit_price` | Guarda cotización; no envía orden |
| `execute_trade` | `quote_id`, `reason`, `stop_loss_percent?`, `stop_slippage="0.03"` | Ejecuta compra/venta y puede autorizar SL |
| `get_portfolio` | — | Saldo y posiciones del modo |
| `get_trade_history` | `limit=50` (1..200), `offset=0` | Órdenes persistidas |
| `settle_paper` | — | Acredita liquidación virtual con ganador oficial |
| `sync_orders` | — | Reconciliación live o liquidación paper |
| `poll_updates` | `after=0`, `limit=100` (1..200) | Sincroniza y entrega eventos |
| `cancel_order` | `local_order_id` | Intenta cancelar en exchange; no revierte fills |
| `set_trading_paused` | `paused` | Pausa total persistente; también SL |
| `set_reduce_only` | `enabled` | Permite salidas y bloquea compras |
| `set_stop_loss` | `local_order_id`, `loss_percent?`, `trigger_price?`, `slippage="0.03"` | Autoriza SL; exactamente un tipo de disparador |
| `list_stop_losses` | `active_only=false`, `limit=100`, `offset=0` | Consulta SL activos/históricos |
| `cancel_stop_loss` | `stop_id` | Desactiva futuros envíos del SL |
| `get_movements` | `after=0`, `limit=100`, `kind?`, `slug?` | Auditoría local filtrada; sin sincronizar |
| `get_market_context` | `slug` | Reglas y referencias TWAP 30/60s persistidas |
| `get_price_history` | `asset`, `window=30`, `since?`, `limit=500` | Serie local; ventana 30/60, límite 1..1000 |
| `record_forecast` | `slug`, `outcome`, `probability`, `reason` | Guarda probabilidad 0..1 antes del cierre |
| `get_metrics` | — | Ejecución, latencias, errores y calibración |

Decimales de trading y probabilidades se pasan como cadenas. `since` es un timestamp Unix en segundos UTC. Activos: `btc`, `eth`, `sol`, `xrp`; resultados: `up`, `down`; lados: `BUY`, `SELL`. `get_price_history` devuelve puntos en orden ascendente desde `since`, por defecto la última hora.

## Errores de recuperación

| Código | Acción |
| --- | --- |
| `QUOTE_NOT_FOUND` | Revisar ID/modo/base |
| `QUOTE_EXPIRED`, `QUOTE_CHANGED` | Obtener nueva cotización si no hubo envío |
| `INSUFFICIENT_LIQUIDITY`, `STALE_BOOK` | Esperar datos/liquidez y volver a consultar |
| `ORDER_UNKNOWN` | Reconciliar; no crear otra intención para el mismo envío |
| `ORDER_PENDING` | Esperar finalización de la venta pendiente |
| `BET_LIMIT`, `DAILY_LIMIT` | Reducir importe o esperar; no eludir el límite |
| `MARKET_EXPOSURE_LIMIT`, `ASSET_EXPOSURE_LIMIT`, `POSITION_LIMIT` | Revisar exposición |
| `TRADING_PAUSED`, `REDUCE_ONLY` | Respetar el modo indicado por el usuario |
| `STOP_EXISTS` | Consultar el SL actual; cancelar antes de reemplazar |
| `INVENTORY_CHANGED` | Recalcular cantidad de salida |
| `PUBLIC_API_ERROR` | Consultar de nuevo según `retryable` |
| `INTERNAL_ERROR` | Buscar `correlation_id` en `get_metrics` / `tool_calls` |

Los cambios de estado de una orden se devuelven como comprobantes, aunque el estado sea `rejected` o `unknown`: revisar `data.status`, no sólo `ok`. El error genérico no expone cuerpos remotos, claves, firmas ni argumentos originales.

`record_forecast` registra cada llamada como observación independiente; no es idempotente. El score Brier usa la probabilidad asignada al resultado indicado y el ganador oficial. No es una medida de rentabilidad y varias predicciones sobre un mismo mercado están correlacionadas.
