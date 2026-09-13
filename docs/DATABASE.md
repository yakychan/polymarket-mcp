# Base de datos y auditoría

SQLite local, WAL y `synchronous=FULL`. Las tablas existentes de 0.1 se conservan. El arranque agrega tablas e índices mediante `CREATE ... IF NOT EXISTS`, sin vaciar cuentas. `PRAGMA user_version` identifica el esquema actual como 2.

## Tablas

| Tabla | Contenido |
| --- | --- |
| `state` | Saldos paper, pausa/reduce-only por modo, wallet live, heartbeat |
| `quotes` | Cotizaciones persistentes e identificadores de intención |
| `orders` | Último estado acumulado por orden; `quote_id` único |
| `positions` | Inventario, coste y liquidaciones paper |
| `events` | Auditoría ordenada por secuencia de compras, ventas, fills, SL, pausas y pronósticos |
| `stops` | Configuración, estado, vínculo a compra/salida y errores del SL |
| `observations` | TWAP públicos: símbolo, ventana, instante observado/recibido y valor decimal |
| `forecasts` | Probabilidades y motivos registrados antes del cierre |
| `resolutions` | Ganador oficial por condición |
| `snapshots` | Mejor bid/ask, timestamps y comisiones al solicitar snapshots |
| `tool_calls` | Herramienta, duración, código y diagnóstico seguro por correlación |

Paper/live comparten archivo pero filtran órdenes, eventos, stops y pronósticos por modo. Las observaciones y los ganadores son públicos y compartidos. No se almacenan firmas ni claves; los motivos son texto libre y podrían contener información privada que haya escrito el usuario.

## Consulta desde el MCP

- `get_trade_history(limit, offset)`: órdenes recientes con sus estados y ejecución acumulada.
- `get_movements(after, limit, kind, slug)`: eventos, sin consultas externas ni liquidación. Guardar `next_cursor`; `has_more` indica otra página.
- `poll_updates(after, limit)`: sincroniza primero y luego entrega novedades.
- `list_stop_losses`: historial de SL y sus intentos.
- `get_price_history`: observaciones recibidas localmente; no reconstruye huecos.
- `get_metrics`: conteos, latencias, slippage y Brier cuando hay resoluciones oficiales.

El cursor es global y creciente: puede haber saltos porque se filtra por modo/tipo/mercado. Mantener cursores separados por combinación de filtros. Un evento `order_update` no es otra compra; el campo `execution` de cada orden es acumulativo. No sumar todos los eventos como si fueran débitos. Para saldos paper usar `get_portfolio`; la comisión real live puede ser desconocida.

## SQL de sólo lectura

Abrir la base en modo lectura con una herramienta SQLite. Ejemplos:

```sql
SELECT id, datetime(created, 'unixepoch') AS utc,
       json_extract(body, '$.market.slug') AS mercado,
       json_extract(body, '$.side') AS lado,
       json_extract(body, '$.status') AS estado,
       json_extract(body, '$.execution.notional_usd') AS nominal
FROM orders WHERE mode = 'paper' ORDER BY created DESC LIMIT 100;

SELECT seq, datetime(created, 'unixepoch') AS utc, kind, body
FROM events WHERE mode = 'paper' AND seq > 0 ORDER BY seq LIMIT 100;

SELECT id, status, json_extract(body, '$.last_error') AS ultimo_error
FROM stops WHERE mode = 'paper';

SELECT observed, value FROM observations
WHERE symbol = 'btc/usd' AND window = 30 ORDER BY observed DESC LIMIT 100;

SELECT observed, body FROM snapshots
WHERE mode = 'paper' AND slug = 'SLUG' ORDER BY observed DESC LIMIT 100;
```

Los importes se guardan como texto decimal para no perder precisión. No usar conversiones a `REAL` como contabilidad de referencia. `observed` de Chainlink es el reloj de la fuente; `received` y los eventos usan el reloj local. El motor calibra sus validaciones con el reloj del exchange, por lo que ambos timestamps pueden diferir si el equipo está desfasado.

## Backup y restauración

`scripts/backup_db.py` utiliza la API de backup SQLite y verifica integridad. Funciona con WAL activo; copiar sólo `.sqlite3` mientras el servidor escribe puede omitir datos. El script no sobrescribe destinos.

Para restaurar, detener todos los MCP y workers que utilizan esa base y conservar una copia de los archivos actuales. Una copia antigua de una cuenta live puede omitir órdenes reales posteriores: antes de reanudar envíos hay que reconciliar esa actividad con el exchange. No restaurar y activar automáticamente los SL de una copia antigua como si fuera la cuenta actual. No se incluye una operación automática de rollback live.

El historial financiero no se purga automáticamente. Las observaciones, cotizaciones, snapshots y diagnósticos también crecen con el uso. Controlar tamaño del archivo y archivar copias periódicas. No eliminar filas de órdenes, fills o stops activos para liberar espacio: intervienen en idempotencia y exposición.
