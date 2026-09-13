# Cambios

## 0.2.0 — 2026-09-13

- Clasificación de rechazos CLOB conocidos sin convertirlos en timeouts inciertos.
- Recuperación de fills aunque consultar la orden devuelva 404; deduplicación, finalización fallida y confirmación parcial.
- Herramientas ejecutadas fuera del bucle asíncrono; validación remota fuera del bloqueo de escritura SQLite y lecturas no exclusivas.
- Errores MCP con `isError`, códigos, identificador de correlación y diagnósticos sin cuerpos remotos ni credenciales.
- Exposición máxima por mercado/activo, máximo de posiciones, presupuesto visible y modo de reducción de posiciones.
- Stop-loss local optativo y persistente, monitor autónomo, bloqueo entre procesos y modo `--worker`.
- Auditoría consultable por cursor/filtros, backup consistente y esquema SQLite aditivo.
- Colector Chainlink TWAP 30/60s con reconexión, contexto temporal, pronósticos y métricas de calibración/ejecución.
- Documentación portable, ejemplos, pruebas de regresión, flujo CI y ZIP mediante lista permitida.

Los procesos 0.1 deben reiniciarse. No se migran o eliminan credenciales ni historiales existentes. Los stops no se crean automáticamente para compras previas.
