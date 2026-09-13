# Arquitectura y recuperación

## Componentes

```text
Cliente MCP ──stdio── server.py ──hilos── Engine
                                        ├── PublicAPI: Gamma/CLOB/Data
                                        ├── LiveBroker: firma/envío/reconciliación
                                        └── Store: SQLite + auditoría
Monitor (un propietario por DB/modo) ── Stops ── Engine.execute
                                  └── mantenimiento: sync/resoluciones
Colector RTDS (un propietario por DB) ── observations
Insights ── referencias temporales, pronósticos y métricas
```

Las funciones de herramientas se ejecutan mediante `anyio.to_thread.run_sync`; una consulta lenta no bloquea el bucle de eventos MCP. El cierre espera las operaciones ya en curso. Las lecturas SQLite usan `BEGIN`, y las secciones que reservan fondos/intenciones usan `BEGIN IMMEDIATE`.

## Envío e idempotencia

1. Leer la cotización o devolver el comprobante existente por `quote_id`.
2. Consultar mercado, comisiones, libro, saldo y geoblock, y preparar la firma fuera del bloqueo SQLite.
3. En una transacción corta, volver a comprobar idempotencia, pausa, exposición, antigüedad y vencimiento; reservar la orden y su hash. Si corresponde, guardar el SL junto con la compra.
4. Hacer el POST después del commit.
5. Guardar respuesta o estado incierto, sin degradar una reconciliación más reciente.

Una caída en los pasos 3/4 puede dejar una intención sin enviar. No se guarda la firma ni se reenvía al reiniciar: la ambigüedad se conserva. Un timeout del cliente no cancela un envío ya realizado. La recuperación reutiliza el ID existente.

Para ventas, una orden pendiente del mismo token impide otro envío del MCP. El SL vuelve a verificar su autorización y el inventario dentro de la reserva, por lo que una cancelación o venta manual previa al commit puede bloquear la salida.

## Reconciliación

Se consulta la orden y sus trades; un 404 de la orden no evita buscar trades. Se filtra por hash taker y se valida identidad de token, mercado y lado cuando está presente. Los fills se deduplican por ID y no se pierde una confirmación conocida por una lectura posterior incompleta.

Sólo se registran cantidades ejecutadas de fills `CONFIRMED`. Si se acredita cobertura completa del `size_matched` remoto, todos confirmados → `confirmed`; todos fallidos → `failed`; mezcla terminal → `partially_confirmed`. También se puede acreditar cobertura sin orden remota cuando los IDs de todos los trades coinciden exactamente con los recibidos en el POST aceptado. Una cobertura incompleta conserva un estado pendiente o incierto. Los importes de `execution` son acumulativos por orden.

Rechazos HTTP 400 conocidos durante el POST se convierten en `rejected`. Mensajes desconocidos, duplicados, timeouts y 5xx no se interpretan automáticamente como ausencia de ejecución. No hay un botón que borre la incertidumbre sin evidencia.

## Monitor y feeds

Los archivos de bloqueo usan `msvcrt` en Windows y `flock` en sistemas POSIX. El bloqueo dura mientras el propietario vive, no depende de un TTL susceptible de vencer durante una consulta. No se deben borrar manualmente esos archivos en ejecución.

El monitor usa un hilo de mantenimiento separado para reconciliación/resoluciones, mientras evalúa stops en su propio ciclo. El colector RTDS tiene reconexión y heartbeat, y guarda valores E18 mediante aritmética decimal. Las ventanas 30/60s son referencias separadas; la selección aplicable depende de las reglas del mercado.

Los timestamps de recepción son locales y los observados pertenecen a la fuente. La frescura de los libros y el contexto de mercado usan tiempo calibrado con CLOB. Sin observación inicial suficientemente cercana, el cambio desde apertura queda como `null`.

## Operación

Los logs de errores incluyen tipo, función, línea y correlación, sin texto de excepción remoto ni variables locales. Las herramientas registran duración/código en SQLite. Los stops registran motivos de espera en su auditoría y el monitor informa heartbeat.

Los límites sólo contemplan actividad de esta base. Todos los procesos de una misma cuenta deben usar la misma base y configuración. No usar SQLite en red ni duplicar bases para operar simultáneamente. No hay HTTP público, gestión remota de claves, redeem, ni supervisión automática del sistema operativo.
