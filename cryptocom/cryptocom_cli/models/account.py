"""Private account models for Crypto.com Exchange."""
from enum import Enum
from typing import List, Optional, Union

from pydantic import Field

from .market import ExchangeModel


class OrderSide(str, Enum):
    """Known order sides."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Known open order types."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LIMIT = "STOP_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"


class TimeInForce(str, Enum):
    """Known time-in-force values."""

    GOOD_TILL_CANCEL = "GOOD_TILL_CANCEL"
    IMMEDIATE_OR_CANCEL = "IMMEDIATE_OR_CANCEL"
    FILL_OR_KILL = "FILL_OR_KILL"


class OrderStatus(str, Enum):
    """Known open order statuses."""

    NEW = "NEW"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"


class PositionBalance(ExchangeModel):
    """Collateral position balance inside private/user-balance."""

    instrument_name: str
    quantity: Optional[str] = None
    market_value: Optional[str] = None
    collateral_eligible: Optional[Union[bool, str]] = None
    haircut: Optional[str] = None
    collateral_amount: Optional[str] = None
    max_withdrawal_balance: Optional[str] = None
    reserved_qty: Optional[str] = None


class AccountBalance(ExchangeModel):
    """Balance row returned by private/user-balance."""

    instrument_name: str
    total_available_balance: Optional[str] = None
    total_margin_balance: Optional[str] = None
    total_initial_margin: Optional[str] = None
    total_position_im: Optional[str] = None
    total_haircut: Optional[str] = None
    total_maintenance_margin: Optional[str] = None
    total_position_cost: Optional[str] = None
    total_cash_balance: Optional[str] = None
    total_collateral_value: Optional[str] = None
    total_session_unrealized_pnl: Optional[str] = None
    total_session_realized_pnl: Optional[str] = None
    total_effective_leverage: Optional[str] = None
    position_limit: Optional[str] = None
    used_position_limit: Optional[str] = None
    total_isolated_cash_balance: Optional[str] = None
    is_liquidating: Optional[bool] = None
    position_balances: List[PositionBalance] = Field(default_factory=list)
    isolated_positions: List[dict] = Field(default_factory=list)


class OpenOrder(ExchangeModel):
    """Open order returned by private/get-open-orders."""

    account_id: str
    order_id: str
    client_oid: Optional[str] = None
    order_type: Optional[OrderType] = None
    time_in_force: Optional[TimeInForce] = None
    side: Optional[OrderSide] = None
    exec_inst: List[str] = Field(default_factory=list)
    quantity: Optional[str] = None
    limit_price: Optional[str] = None
    order_value: Optional[str] = None
    maker_fee_rate: Optional[str] = None
    taker_fee_rate: Optional[str] = None
    avg_price: Optional[str] = None
    cumulative_quantity: Optional[str] = None
    cumulative_value: Optional[str] = None
    cumulative_fee: Optional[str] = None
    status: Optional[OrderStatus] = None
    update_user_id: Optional[str] = None
    order_date: Optional[str] = None
    instrument_name: Optional[str] = None
    fee_instrument_name: Optional[str] = None
    create_time: Optional[int] = None
    create_time_ns: Optional[str] = None
    update_time: Optional[int] = None
    isolation_id: Optional[str] = None
    isolation_type: Optional[str] = None
