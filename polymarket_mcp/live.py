import logging
from threading import RLock
from decimal import Decimal

from py_clob_client_v2 import ApiCreds, ClobClient, MarketOrderArgs, OrderType, PartialCreateOrderOptions
from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams, TradeParams, OrderPayload
from py_clob_client_v2.config import get_contract_config
from py_clob_client_v2.order_utils.exchange_order_builder_v2 import ExchangeOrderBuilderV2
from py_clob_client_v2.exceptions import PolyApiException

from .config import TradingError, decimal


class LiveBroker:
    def __init__(self, settings):
        if settings.mode != "live":
            raise TradingError("El broker real sólo se puede construir en live.")
        # El SDK puede registrar cuerpos de errores remotos. No enviarlos al cliente/log.
        logging.getLogger("py_clob_client_v2.http_helpers.helpers").disabled = True
        self.settings = settings
        self.prepare_lock = RLock()
        self.client = ClobClient(
            host="https://clob.polymarket.com", chain_id=137, key=settings.private_key,
            creds=ApiCreds(settings.api_key, settings.api_secret, settings.api_passphrase),
            signature_type=settings.signature_type, funder=settings.funder or None,
            use_server_time=True, retry_on_error=False,
        )

    @property
    def wallet(self):
        return self.settings.funder or self.client.get_address()

    def balance(self, token=None):
        result = self.client.get_balance_allowance(BalanceAllowanceParams(
            asset_type=AssetType.CONDITIONAL if token else AssetType.COLLATERAL,
            token_id=token, signature_type=self.settings.signature_type,
        ))
        return {"balance": str(decimal(result["balance"]) / Decimal(10**6)),
                "allowances_raw": result.get("allowances", {})}

    def prepare(self, quote):
        # El SDK muta caches al preparar; serializar sólo esta sección, nunca SQLite.
        with self.prepare_lock:
            return self._prepare(quote)

    def _prepare(self, quote):
        signed = self.client.create_market_order(
            MarketOrderArgs(token_id=quote["token"], amount=float(quote["amount"]),
                            side=quote["side"], price=float(quote["limit_price"]), order_type=OrderType.FOK),
            PartialCreateOrderOptions(tick_size=quote["tick_size"], neg_risk=quote["neg_risk"]),
        )
        # Guardamos el hash ANTES del POST: permite investigar timeouts sin repetir la apuesta.
        if not hasattr(signed, "timestamp"):
            raise TradingError("El SDK no generó una orden V2; operación bloqueada.")
        config = get_contract_config(137)
        contract = config.neg_risk_exchange_v2 if quote["neg_risk"] else config.exchange_v2
        builder = ExchangeOrderBuilderV2(contract, 137, self.client.signer)
        order_id = builder.build_order_hash(builder.build_order_typed_data(signed))
        return signed, order_id

    def submit(self, signed):
        try:
            return self.client.post_order(signed, OrderType.FOK)
        except PolyApiException as exc:
            # Sólo rechazos inequívocos. Duplicados, 5xx y respuestas desconocidas
            # pueden referir a una orden ya aceptada y permanecen inciertos.
            message = exc.error_msg
            message = message.get("error", "") if isinstance(message, dict) else ""
            known = ("fok orders are filled or killed", "not enough balance / allowance",
                     "invalid order payload", "invalid signature", "invalid order expiration",
                     "order is below the minimum", "invalid price", "invalid tick size")
            if exc.status_code == 400 and any(x in message.lower() for x in known):
                return {"success": False, "status": "rejected", "error_code": "EXCHANGE_REJECTED"}
            raise

    def reconcile(self, order_id, condition_id):
        order = None
        try:
            order = self.client.get_order(order_id)
        except PolyApiException as exc:
            if exc.status_code != 404:
                raise
        trades = self.client.get_trades(TradeParams(market=condition_id))
        # Sólo órdenes taker FOK emitidas por este MCP; no mezclar trades de otras órdenes.
        fills = [t for t in trades if t.get("taker_order_id") == order_id]
        return order, fills

    def cancel(self, order_id):
        return self.client.cancel_order(OrderPayload(orderID=order_id))
