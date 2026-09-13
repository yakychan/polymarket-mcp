# Validación de la versión 0.2.0

Realizada el 13 de septiembre de 2026 en Windows con Python 3.13.

- `python -m pytest -q -p no:cacheprovider`: **65 pruebas aprobadas**.
- `python -m pip check`: sin incompatibilidades declaradas.
- `scripts/smoke_public.py`: descubrimiento y compra paper con profundidad real, en base temporal aislada; idempotencia verificada.
- `scripts/smoke_feed.py --seconds 15`: recepción y persistencia de observaciones Chainlink TWAP de 30 y 60 segundos, con precisión decimal.
- Archivo compartible: lista de archivos permitidos, integridad ZIP, ejemplos JSON/TOML y enlaces locales de documentación comprobados por tests.

La suite cubre contabilidad paper, liquidación oficial, firma V2 de fixture, handshake stdio, errores MCP, rechazo/timeout, fills duplicados y parciales, recuperación por 404, exposición, concurrencia, SL optativo, reinicios, salida autónoma, pausa, cancelación, precio mínimo, polvo, venta manual durante preparación, límites de cantidad, backup, historial y filtrado de diagnósticos.

Las credenciales y la base operativa del usuario no se usan en las pruebas. No se enviaron órdenes live. La integración live se valida con SDK local y broker simulado; eso no sustituye una validación operativa de fondos, allowances, firma de cada tipo de wallet y conectividad del destinatario. La matriz CI Linux/Windows está preparada, pero no se afirma que haya sido ejecutada remotamente.
