from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


class TradingError(Exception):
    """Error seguro para mostrar al cliente MCP, sin secretos."""

    def __init__(self, message, code="VALIDATION_ERROR", retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def decimal(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise TradingError("Número decimal inválido.") from None
    if not result.is_finite():
        raise TradingError("El número debe ser finito.")
    return result


@dataclass(frozen=True)
class Settings:
    mode: str = "paper"
    database: Path = ROOT / "data/trading.sqlite3"
    initial_balance: Decimal = Decimal("1000")
    max_bet: Decimal = Decimal("10")
    daily_spend: Decimal = Decimal("100")
    market_exposure: Decimal = Decimal("25")
    asset_exposure: Decimal = Decimal("50")
    max_positions: int = 10
    monitor_interval: int = 2
    feed_enabled: bool = True
    quote_ttl: int = 20
    close_buffer: int = 15
    book_age: int = 15
    assets: tuple[str, ...] = ("btc", "eth", "sol", "xrp")
    private_key: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)
    api_passphrase: str = field(default="", repr=False)
    signature_type: int = 0
    funder: str = ""

    def __post_init__(self):
        if self.mode not in ("paper", "live"):
            raise TradingError("OPERATION_MODE debe ser paper o live; no se inició el servidor.")
        if any(not x.is_finite() or x <= 0 for x in (self.initial_balance, self.max_bet, self.daily_spend, self.market_exposure, self.asset_exposure)):
            raise TradingError("Los saldos y límites deben ser positivos y finitos.")
        if not 1 <= self.quote_ttl <= 60 or not 1 <= self.book_age <= 60 or not 1 <= self.close_buffer < 300:
            raise TradingError("Configuración de tiempos inválida.")
        if not 1 <= self.max_positions <= 1000 or not 1 <= self.monitor_interval <= 30:
            raise TradingError("MAX_OPEN_POSITIONS o MONITOR_INTERVAL_SECONDS inválido.")
        if not self.assets or not set(self.assets) <= {"btc", "eth", "sol", "xrp"}:
            raise TradingError("ALLOWED_ASSETS admite btc,eth,sol,xrp.")
        if self.signature_type not in (0, 1, 2, 3):
            raise TradingError("POLYMARKET_SIGNATURE_TYPE debe ser 0, 1, 2 o 3.")
        if self.mode == "live":
            if not all((self.private_key, self.api_key, self.api_secret, self.api_passphrase)):
                raise TradingError("live requiere WALLET_PRIVATE_KEY y las tres credenciales POLYMARKET_API_*.")
            if self.signature_type and not self.funder:
                raise TradingError("La wallet proxy/Safe/deposit requiere POLYMARKET_FUNDER_ADDRESS.")

    @classmethod
    def load(cls, env_path: Path | None = None):
        # El archivo elegido tiene prioridad: OPERATION_MODE del .env es la autoridad.
        path = Path(env_path or os.environ.get("POLYMARKET_ENV_FILE", ROOT / ".env"))
        if (env_path or os.environ.get("POLYMARKET_ENV_FILE")) and not path.is_file():
            raise TradingError("No existe el archivo POLYMARKET_ENV_FILE indicado.", "CONFIG_ERROR")
        values = {**os.environ, **{k: v for k, v in dotenv_values(path).items() if v is not None}}
        def get(key, default=""):
            return str(values.get(key, default)).strip()
        database = Path(get("DATABASE_PATH", "data/trading.sqlite3"))
        if get("ENABLE_CHAINLINK_FEED", "true").lower() not in ("true", "false"):
            raise TradingError("ENABLE_CHAINLINK_FEED debe ser true o false.", "CONFIG_ERROR")
        try:
            return cls(
                mode=get("OPERATION_MODE", "paper"),
                database=database if database.is_absolute() else path.resolve().parent / database,
                initial_balance=decimal(get("PAPER_INITIAL_BALANCE", "1000")),
                max_bet=decimal(get("MAX_BET_USD", "10")),
                daily_spend=decimal(get("MAX_DAILY_SPEND_USD", "100")),
                market_exposure=decimal(get("MAX_MARKET_EXPOSURE_USD", "25")),
                asset_exposure=decimal(get("MAX_ASSET_EXPOSURE_USD", "50")),
                max_positions=int(get("MAX_OPEN_POSITIONS", "10")),
                monitor_interval=int(get("MONITOR_INTERVAL_SECONDS", "2")),
                feed_enabled=get("ENABLE_CHAINLINK_FEED", "true").lower() == "true",
                quote_ttl=int(get("QUOTE_TTL_SECONDS", "20")),
                close_buffer=int(get("MIN_SECONDS_TO_CLOSE", "15")),
                book_age=int(get("MAX_BOOK_AGE_SECONDS", "15")),
                assets=tuple(x.strip().lower() for x in get("ALLOWED_ASSETS", "btc,eth,sol,xrp").split(",")),
                private_key=get("WALLET_PRIVATE_KEY"), api_key=get("POLYMARKET_API_KEY"),
                api_secret=get("POLYMARKET_API_SECRET"), api_passphrase=get("POLYMARKET_API_PASSPHRASE"),
                signature_type=int(get("POLYMARKET_SIGNATURE_TYPE", "0")),
                funder=get("POLYMARKET_FUNDER_ADDRESS"),
            )
        except ValueError:
            raise TradingError("Una variable numérica del .env es inválida.") from None
