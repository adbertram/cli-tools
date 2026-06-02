"""Market data models for Crypto.com Exchange."""
from enum import Enum
from typing import List, Optional, Union

from pydantic import ConfigDict

from .base import CLIModel


class ExchangeModel(CLIModel):
    """Base model that preserves unknown API response fields."""

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class InstrumentType(str, Enum):
    """Known Crypto.com Exchange instrument types."""

    CCY_PAIR = "CCY_PAIR"
    SPOT = "SPOT"
    PERPETUAL_SWAP = "PERPETUAL_SWAP"
    FUTURE = "FUTURE"
    WARRANT = "WARRANT"


class Instrument(ExchangeModel):
    """Instrument returned by public/get-instruments."""

    symbol: str
    inst_type: Optional[InstrumentType] = None
    display_name: Optional[str] = None
    base_ccy: Optional[str] = None
    quote_ccy: Optional[str] = None
    quote_decimals: Optional[int] = None
    quantity_decimals: Optional[int] = None
    price_tick_size: Optional[str] = None
    qty_tick_size: Optional[str] = None
    max_leverage: Optional[str] = None
    tradable: Optional[bool] = None
    expiry_timestamp_ms: Optional[int] = None
    beta_product: Optional[bool] = None
    underlying_symbol: Optional[str] = None
    contract_size: Optional[str] = None
    margin_buy_enabled: Optional[bool] = None
    margin_sell_enabled: Optional[bool] = None


class Ticker(ExchangeModel):
    """Ticker returned by public/get-tickers."""

    i: str
    t: int
    h: Optional[str] = None
    l: Optional[str] = None
    a: Optional[str] = None
    v: Optional[str] = None
    vv: Optional[str] = None
    oi: Optional[str] = None
    c: Optional[str] = None
    b: Optional[str] = None
    k: Optional[str] = None


class Trade(ExchangeModel):
    """Trade returned by public/get-trades."""

    d: str
    t: int
    tn: Union[int, str]
    q: str
    p: str
    s: str
    i: str
    m: Optional[Union[int, str]] = None


class Candlestick(ExchangeModel):
    """Candlestick returned by public/get-candlestick."""

    o: str
    h: str
    l: str
    c: str
    v: str
    t: int


class BookSnapshot(ExchangeModel):
    """Order book snapshot returned by public/get-book."""

    instrument_name: str
    depth: int
    bids: List[List[str]]
    asks: List[List[str]]
    t: int
