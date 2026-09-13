# Compartir y actualizar

## Preparar un paquete

Desde la carpeta del proyecto:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/build_share.py
```

Se crea `dist/polymarket-mcp-0.2.0.zip` y se imprime su SHA256. El script no sobrescribe otro ZIP. Para otra compilación:

```powershell
.\.venv\Scripts\python.exe scripts/build_share.py --output dist/polymarket-mcp-0.2.0-revision.zip
```

La lista permitida incluye código del MCP, tests, scripts, documentación, ejemplos, metadatos y `.env.example`. Se excluyen `.env`, `data/`, configuraciones personales del cliente, entornos, bases, logs, backups, archivos ZIP previos y bots heredados. No publicar la carpeta de trabajo completa. Los archivos nuevos incluidos en esas carpetas permitidas también deben revisarse antes de distribuir futuras versiones.

Entregar el ZIP y el hash. El destinatario descomprime, sigue el README, instala dependencias y crea un `.env` propio. Los ejemplos tienen rutas ficticias que debe reemplazar. El paquete no registra automáticamente servidores ni configura una wallet. No se ha publicado en un registro de paquetes ni en un repositorio remoto.

## Actualizar desde 0.1

1. Consultar el estado y las órdenes pendientes. Conservar copia consistente de la base.
2. Detener los procesos MCP/workers antiguos que usan esa base.
3. Actualizar código e instalar con `python -m pip install -e ".[dev]"`.
4. Conservar el `.env` existente; revisar los nuevos límites por mercado/activo/posiciones. Los valores predeterminados pueden bloquear nuevas compras antes permitidas.
5. Iniciar una nueva conexión MCP y verificar `get_status`, `get_trade_history` y `list_stop_losses`.

La base se amplía de forma aditiva al arrancar. Las compras anteriores siguen registradas; no se les agrega SL sin un pedido explícito. Las órdenes ambiguas continúan pendientes de reconciliación. No ejecutar procesos viejos y nuevos simultáneamente durante una actualización.

## Verificación

Las pruebas unitarias y de protocolo son locales y usan cuentas temporales. Los smoke tests de libro y RTDS requieren internet. Una prueba pública puede fallar por ausencia de liquidez, cierre próximo, indisponibilidad o falta de observaciones. Nunca convertir esos errores en un resultado de trading simulado exitoso.

La configuración CI incluida ejecuta tests en Windows y Ubuntu con Python 3.11/3.13 cuando se suba a un repositorio compatible. Eso no significa que esa matriz ya se haya ejecutado durante una instalación local. Las dependencias directas están fijadas; las transitivas las resuelve pip según plataforma.

Para mantener SL al cerrar el cliente, ejecutar `python -m polymarket_mcp --worker` bajo un supervisor del sistema o en una terminal persistente. Configurar reinicio y política de suspensión del equipo según el entorno. No cerrar esa terminal si es el único proceso que monitoriza la cuenta.
