# Stop-loss local

## Activación explícita

Un SL autoriza al monitor a vender sin pedir otra decisión a la IA cuando se cumple el disparador. No autoriza nuevas compras. Debe solicitarlo el usuario y puede cancelarlo con `cancel_stop_loss`.

Al comprar, pasar a `execute_trade`:

```json
{"quote_id":"COTIZACION","reason":"Entrada solicitada","stop_loss_percent":"20","stop_slippage":"0.03"}
```

Para una compra existente, llamar `set_stop_loss` con exactamente uno de estos formatos:

```json
{"local_order_id":"ORDEN_COMPRA","loss_percent":"20","slippage":"0.03"}
```

```json
{"local_order_id":"ORDEN_COMPRA","trigger_price":"0.40","slippage":"0.02"}
```

Hay un único SL activo por token y modo. Para cambiar sus parámetros, cancelar el anterior y crear otro; la cancelación no puede retirar una venta cuyo envío ya quedó reservado. Una respuesta perdida de `set_stop_loss` se investiga con `list_stop_losses` antes de volver a crear.

## Precio y cantidad

`loss_percent` es caída porcentual del precio del token respecto del precio medio de entrada confirmado, sin comisiones. No representa una caída del activo subyacente ni del saldo total de la cuenta. `trigger_price` permite elegir directamente un disparador entre 0 y 1.

El monitor observa el mejor bid disponible: si es menor o igual al disparador, activa la salida. El límite firmado es `disparador - slippage`, redondeado hacia arriba al tick y nunca menor que un tick. `slippage` es una diferencia absoluta de precio por share, no un porcentaje. Por ejemplo, 0,03 son tres centavos por share.

Un spread amplio puede disparar el SL inmediatamente después de comprar. Revisar el bid de salida además del ask de entrada al elegir el porcentaje.

Después de dispararse, el SL permanece activado aunque el precio se recupere. Sigue intentando vender dentro del mismo piso; no lo reduce automáticamente. Cada intento requiere profundidad suficiente para una orden FOK. Si el mercado salta por debajo del piso, la salida puede quedar sin ejecutar.

Se limita a la cantidad asociada a la compra y al inventario restante registrado. Las ventas manuales se atribuyen FIFO para detectar lotes ya cerrados. Las salidas propias tienen además un tope acumulado para que un SL no venda más shares que las protegidas. Con compras múltiples del mismo token, las shares son fungibles: no hay aislamiento de lotes dentro del exchange. La cantidad se redondea hacia abajo a dos decimales y puede quedar polvo.

Sólo se protege actividad del MCP. Ventas manuales fuera del MCP pueden desactualizar la atribución: el saldo real se vuelve a verificar antes de enviar, pero no se reconstruye un historial completo de otros bots.

## Estados

| Estado | Significado |
| --- | --- |
| `armed` | Configurado; puede estar esperando confirmación de entrada |
| `triggered` | Disparador alcanzado; salida pendiente o en revaluación |
| `waiting` | Existe una venta enviada o incierta, a reconciliar |
| `completed` | Cantidad autorizada vendida o lote ya cerrado manualmente |
| `cancelled` | Desactivado, o compra sin ejecución |
| `expired` | Se terminó la ventana operable con cantidad pendiente |
| `dust` | Remanente menor que el mínimo operable |

`last_error`, `attempts`, `quote_id`, `last_exit_order_id` y los eventos `stop_update` permiten investigar. `completed` no significa que una venta respetó exactamente el porcentaje de pérdida solicitado: revisar los fills y sus comisiones.

## Reinicios, pausa y fallos

La intención de salida se vincula a un `quote_id` durable antes de ejecutar. Si el proceso cae, reutiliza esa intención. Un envío `unknown` o `submitting` no se reintenta con otro ID. Rechazos inequívocos permiten otra cotización; cotizaciones vencidas que nunca se enviaron también pueden reemplazarse.

El monitor arranca con el MCP o con `python -m polymarket_mcp --worker`. Un bloqueo OS garantiza un propietario por base/modo y se libera al morir el proceso. Los demás procesos esperan y pueden tomar el relevo. Esto requiere disco local y la misma configuración. No copiar una base activa para ejecutarla en otra máquina: los bloqueos no coordinan copias distintas.

La pausa total bloquea todos los envíos nuevos, incluidos SL. La opción `set_reduce_only(true)` permite vender y mantiene bloqueadas las compras. Una pausa/cancelación no revierte una intención de envío ya reservada ni una ejecución del exchange.

El intervalo predeterminado es dos segundos entre ciclos, no una garantía de latencia. Las consultas, la red, el número de stops, la suspensión del equipo y la carga pueden retrasar la salida. La reconciliación corre aparte del chequeo de SL para que una consulta lenta no detenga otras salidas.

El margen `MIN_SECONDS_TO_CLOSE` también se aplica a los SL. Al entrar en ese margen, un stop sin venta pendiente pasa a `expired`; pueden quedar shares hasta la resolución. Una venta incierta se sigue conservando como pendiente aunque cierre el mercado. Ganadoras live se canjean desde Polymarket.

La ejecución live conserva las validaciones de mercado, identidad, precio, tick, edad del libro, geoblock, saldo y comisiones. El SL no elude esos controles.
