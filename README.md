# Polymarket MCP · 5-minute Up/Down

<p align="center">
  <strong>Paper and live trading tools for Polymarket five-minute Up/Down markets.</strong><br>
  Local MCP server · SQLite audit history · Optional automatic local stop-losses
</p>

<p align="center">
  <a href="README.en.md">English documentation</a> ·
  <a href="docs/TOOLS_en.md">Tool reference</a> ·
  <a href="docs/STOP_LOSS_en.md">Stop-loss guide</a> ·
  <a href="docs/SHARING_en.md">Sharing guide</a>
</p>

This repository provides a local [Model Context Protocol](https://modelcontextprotocol.io/) server for BTC, ETH, SOL, and XRP five-minute Up/Down markets on Polymarket. The connected AI chooses whether to trade; the server validates market data, risk limits, order parameters, persistence, and execution state.

The default mode is **paper**: public market data is real, but funds are virtual. **Live mode signs and submits real CLOB orders** using credentials supplied by the operator. Start in paper mode and review the risk controls before enabling live mode.

| Language | Main guide | Full references |
| --- | --- | --- |
| Español | [README.md](README.md) | [Herramientas](docs/TOOLS.md) · [SL](docs/STOP_LOSS.md) · [Base de datos](docs/DATABASE.md) · [Arquitectura](docs/ARCHITECTURE.md) |
| English | [README.en.md](README.en.md) | [Tools](docs/TOOLS_en.md) · [Stop-loss](docs/STOP_LOSS_en.md) · [Database](docs/DATABASE_en.md) · [Architecture](docs/ARCHITECTURE_en.md) |

## Highlights

- Paper/live separation with persistent, idempotent order receipts.
- Conservative per-trade, daily, market, asset, and position limits.
- SQLite audit trail for quotes, orders, fills, stops, forecasts, resolutions, observations, and diagnostics.
- Optional user-authorized local stop-limit monitor with process locking and restart recovery.
- Chainlink TWAP observations through Polymarket RTDS, with freshness metadata and no invented history.
- MCP errors with stable codes, `isError`, correlation IDs, and secret-safe diagnostics.

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pytest -q
```

Configure the client with [examples/mcp.json](examples/mcp.json) or [examples/codex.toml](examples/codex.toml). The complete setup, configuration table, stop-loss behavior, database backup, and distribution workflow are documented in the language-specific guides above.

## Safety and scope

An automatic stop-loss is a **local stop-limit on the Up/Down token**. It is not an exchange-hosted guarantee and may fail when the market has no liquidity within the configured limit. The monitor must remain running and connected. This project does not create blockchain approvals, transfer funds, or redeem winning positions.

Current validation: 65 automated tests, public paper smoke test, and Chainlink RTDS smoke test. No real live order is submitted by the test suite.

---

## Documentación detallada en español

English version: [README.en.md](README.en.md). Las guías en inglés están junto a cada documento español con el sufijo `_en.md`.

Servidor MCP local en Python para consultar mercados BTC/ETH/SOL/XRP de cinco minutos, operar en paper o live y guardar la actividad en SQLite. La IA del cliente decide las entradas. Un monitor independiente ejecuta únicamente los stop-loss que el usuario solicite.

Versión **0.2.0**. Transporte **stdio**. Requiere Python 3.11 o posterior. El servidor no necesita una API key de un proveedor de IA. Cada persona configura su propia wallet y base de datos; el paquete distribuible no contiene credenciales.

## Instalación rápida

Descomprimir el paquete y abrir una terminal en esa carpeta.

Windows / PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
# Sólo en una instalación nueva: no reemplazar un .env existente.
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m polymarket_mcp --check
```

Linux / macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
# Sólo si todavía no existe .env:
cp -n .env.example .env
.venv/bin/python -m pytest -q
.venv/bin/python -m polymarket_mcp --check
```

El ejemplo usa `OPERATION_MODE=paper`, saldo virtual inicial de USD 1000 y datos públicos reales. `--check` sólo valida configuración y consulta APIs públicas: no inicia el monitor ni firma órdenes. Para uso sin desarrollo se puede instalar con `pip install .`; indicar siempre `POLYMARKET_ENV_FILE` con ruta absoluta si se instala como paquete fuera de la carpeta fuente.

## Conectar un cliente MCP

El cliente debe lanzar el Python del entorno virtual con `run_mcp.py`. Usar rutas absolutas y reiniciar la conexión después de instalar o cambiar el `.env`.

Ejemplo JSON para clientes que aceptan `mcpServers`:

```json
{
  "mcpServers": {
    "polymarket": {
      "command": "C:/ruta/polymarket-mcp/.venv/Scripts/python.exe",
      "args": ["C:/ruta/polymarket-mcp/run_mcp.py"],
      "env": {
        "POLYMARKET_ENV_FILE": "C:/ruta/polymarket-mcp/.env"
      }
    }
  }
}
```

En Linux/macOS, usar `/ruta/polymarket-mcp/.venv/bin/python`. Ajustar la ubicación del archivo JSON según el cliente; ver [ejemplo completo](examples/mcp.json).

### Codex

Fusionar [examples/codex.toml](examples/codex.toml) con la configuración del cliente, reemplazando las rutas. Alternativamente, registrar por CLI:

```powershell
codex mcp add polymarket --env "POLYMARKET_ENV_FILE=C:/ruta/polymarket-mcp/.env" -- "C:/ruta/polymarket-mcp/.venv/Scripts/python.exe" "C:/ruta/polymarket-mcp/run_mcp.py"
```

Las opciones `command`, `args`, `env`, `startup_timeout_sec` y `tool_timeout_sec` están documentadas en [MCP de Codex](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). La política de permisos del cliente sigue aplicándose. No poner claves de wallet en archivos de configuración para compartir.

## Primer uso

Pedido sugerido:

> Consultá modo, saldo, límites y salud del monitor. Analizá BTC Up/Down de cinco minutos con las reglas, el libro y los datos disponibles de Chainlink. Registrá tu probabilidad estimada. Antes de operar, mostrámela junto con la cotización y el motivo. Si te pido SL, configurá sus parámetros y explicame su precio mínimo de salida. Informame los movimientos con sus estados reales.

Flujo habitual: `get_status` → `get_portfolio` → `discover_markets` → `get_market_snapshot` / `get_market_context` → `record_forecast` → `quote_trade` → `execute_trade` → `poll_updates`.

`BUY amount` es nominal en dólares, al que se suma la comisión. `SELL amount` es cantidad de shares. Los importes admiten hasta dos decimales; `limit_price` debe respetar el tick. Todas las órdenes son FOK: ejecución completa dentro del límite o rechazo.

Ejemplo de cotización, usando un slug que exista actualmente:

```json
{"slug":"btc-updown-5m-TIMESTAMP","outcome":"up","side":"BUY","amount":"5.00","limit_price":"0.55"}
```

Para ejecutar con SL optativo:

```json
{"quote_id":"ID_DEVUELTO","reason":"Motivo de la decisión","stop_loss_percent":"20","stop_slippage":"0.03"}
```

La configuración del SL y la intención de compra se guardan en la misma transacción. En live espera confirmación de la entrada para calcular el disparador. Repetir `execute_trade` con el mismo `quote_id` devuelve la misma orden: no crea otra compra ni cambia un SL existente.

## Stop-loss automático

Se puede configurar al comprar o después mediante `set_stop_loss`. Nunca se activa sólo por iniciar el servidor. Por ejemplo, una entrada media a 0,50 con `loss_percent=20` dispara al observar un bid de 0,40 o menor. Con tolerancia absoluta `slippage=0.03`, el precio mínimo de venta es 0,37, ajustado al tick hacia arriba.

Es un **stop-limit local sobre el token Up/Down**, no sobre la cotización de BTC/ETH y no una orden stop alojada en el exchange. El porcentaje excluye comisiones; no garantiza una pérdida máxima ni una salida. Sin liquidez suficiente dentro del límite, el monitor registra el problema y vuelve a evaluar mientras el mercado siga operable. Un timeout con envío incierto se reconcilia y no se reenvía con otra intención.

El monitor vive dentro del proceso MCP. Para mantenerlo funcionando al cerrar el cliente, ejecutar en otra terminal o mediante un supervisor:

```powershell
.\.venv\Scripts\python.exe -m polymarket_mcp --worker
```

Usar el mismo `.env`, modo y `DATABASE_PATH`. Un bloqueo del sistema operativo elige un único monitor por base/modo; otro proceso puede tomar el relevo al salir el primero. El equipo debe permanecer encendido y con conexión. `get_status.monitor` informa heartbeat y salud; `list_stop_losses` muestra los errores de cada SL.

La pausa total detiene compras, ventas nuevas y SL. `set_reduce_only(true)` bloquea compras y permite salidas, salvo que también exista pausa total. Detalles y ejemplos: [Stop-loss](docs/STOP_LOSS.md).

## Historial y base de datos

Todo se guarda en `data/trading.sqlite3` por defecto. La base conserva cotizaciones, órdenes, eventos de movimientos, posiciones paper, stops, pronósticos, resoluciones oficiales, observaciones Chainlink y diagnósticos. Reiniciar no borra el historial ni recarga el saldo paper.

Consultar `get_trade_history` para el estado acumulado de cada orden; `get_movements` para la auditoría con cursor y filtros; `get_metrics` para latencias, fallos, variaciones de precio y evaluación de pronósticos. `poll_updates` además sincroniza y puede liquidar posiciones paper. Los eventos de una misma orden no representan compras adicionales.

La base no contiene claves privadas, firmas ni credenciales. Sí contiene información financiera y motivos escritos por el usuario/IA: tratarla como privada. No ofrece un endpoint de SQL arbitrario.

Crear una copia consistente, incluyendo datos que estén en WAL:

```powershell
.\.venv\Scripts\python.exe scripts/backup_db.py --source data/trading.sqlite3 --output backups/trading-copia.sqlite3
```

El script se niega a sobrescribir un destino existente. Consultas SQL, esquema y precauciones de restauración: [Datos y operación](docs/DATABASE.md).

## Configuración

El `.env` tiene prioridad sobre variables heredadas. `POLYMARKET_ENV_FILE` selecciona otro archivo; si se indica y no existe, el arranque falla. Cambios de configuración requieren reiniciar todos los procesos que usan esa configuración.

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| `OPERATION_MODE` | `paper` | `paper` o `live`; ningún tool cambia el modo |
| `DATABASE_PATH` | `data/trading.sqlite3` | Relativa al `.env` o absoluta |
| `PAPER_INITIAL_BALANCE` | `1000` | Sólo al crear la cuenta paper |
| `MAX_BET_USD` | `10` | Máximo por compra, con reserva de comisión |
| `MAX_DAILY_SPEND_USD` | `100` | Compras por día UTC; ventas no lo reinician |
| `MAX_MARKET_EXPOSURE_USD` | `25` | Coste abierto y reservas por mercado |
| `MAX_ASSET_EXPOSURE_USD` | `50` | Coste abierto y reservas por activo |
| `MAX_OPEN_POSITIONS` | `10` | Tokens con posición o compra pendiente |
| `QUOTE_TTL_SECONDS` | `20` | Vigencia de la cotización |
| `MIN_SECONDS_TO_CLOSE` | `15` | Últimos segundos en que ya no se opera, incluido SL |
| `MAX_BOOK_AGE_SECONDS` | `15` | Antigüedad máxima del libro |
| `MONITOR_INTERVAL_SECONDS` | `2` | Pausa entre ciclos; se suma el trabajo y la latencia |
| `ENABLE_CHAINLINK_FEED` | `true` | Recolectar TWAP públicos de 30/60 segundos |
| `ALLOWED_ASSETS` | `btc,eth,sol,xrp` | Activos admitidos |

La exposición sólo cubre movimientos registrados por este MCP. Los fills live confirmados tienen coste nominal conocido; la comisión efectiva puede faltar. Mientras una compra esté pendiente se reserva su débito completo, incluso si ya hay fills parciales, de forma conservadora. Las resoluciones oficiales liberan exposición de mercados terminados. Rechazos verificables y fallos completos liberan presupuesto; cancelaciones conservan la reserva diaria.

En live configurar `WALLET_PRIVATE_KEY`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, `POLYMARKET_API_PASSPHRASE`, `POLYMARKET_SIGNATURE_TYPE` y, si corresponde, `POLYMARKET_FUNDER_ADDRESS`. Tipos 1/2/3 requieren funder. La base live queda vinculada a la wallet: usar otra base para otra wallet. No compartir la misma base entre configuraciones con distintos activos o límites. SQLite debe estar en disco local, no en una carpeta sincronizada o unidad de red.

Este MCP no crea approvals, transfiere fondos ni ejecuta redeem. `POLYGON_RPC_URL` está reservado y no se utiliza. El canje de posiciones ganadoras live se realiza desde Polymarket. Se verifica geoblock antes de enviar.

## Herramientas y límites conocidos

La [referencia de 21 herramientas](docs/TOOLS.md) detalla parámetros, errores y efectos. La [arquitectura](docs/ARCHITECTURE.md) describe concurrencia y recuperación.

- Paper usa profundidad y comisiones, pero no reproduce competencia por liquidez, todos los redondeos ni la latencia del exchange. Un resultado paper no acredita rentabilidad live.
- `submitted` y `MATCHED` no son liquidación confirmada. Los fills se reconocen al llegar a `CONFIRMED`. Si falta la orden remota, se conserva evidencia de fills confirmados, pero se mantiene `unknown` hasta verificar cobertura completa.
- Una caída entre guardar la intención y hacer el POST deja `submitting`. Se conserva y se investiga; no hay reenvío automático ni herramienta para declararla rechazada sin evidencia.
- RTDS no proporciona historial previo ni replay: la serie empieza cuando el colector recibe datos. Hay indicadores de antigüedad y ausencia de referencia inicial. No se deduce un ganador de esas observaciones.
- Posiciones live de Data API: hasta 500, con posible demora. PnL neto live completo y comisión efectiva por fill no están disponibles en esta versión.
- Las entradas nuevas requieren llamadas del cliente. El monitor sólo reconcilia, recopila datos y ejecuta SL ya autorizados. No envía mensajes a Telegram ni a otros chats.

## Pruebas y distribución

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/smoke_public.py
.\.venv\Scripts\python.exe scripts/smoke_feed.py --seconds 15
.\.venv\Scripts\python.exe scripts/build_share.py
```

Los tests usan bases temporales y un broker simulado. La firma V2 se prueba con una clave pública de fixture, nunca con la wallet del usuario. Los smoke tests consultan servicios públicos y no leen `.env`; la compra smoke es virtual. No se valida live enviando dinero real.

`build_share.py` crea un ZIP mediante una lista explícita de archivos. Compartir ese ZIP, no comprimir toda la carpeta de trabajo: se excluyen `.env`, bases, configuraciones personales, backups, bots heredados y entorno virtual. Cada destinatario instala las dependencias y crea su propio `.env`. Ver [guía de distribución y actualización](docs/SHARING.md).

Referencias oficiales: [SDK CLOB V2](https://github.com/Polymarket/py-clob-client-v2), [ciclo de órdenes](https://docs.polymarket.com/concepts/order-lifecycle), [errores CLOB](https://docs.polymarket.com/resources/error-codes), [Chainlink TWAP](https://docs.polymarket.com/market-data/chainlink-twap), [errores MCP](https://modelcontextprotocol.io/specification/2025-11-25/server/tools). Integraciones consultadas el 13 de septiembre de 2026.
