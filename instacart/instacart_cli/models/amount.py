"""Amount model for monetary values in Instacart CLI."""
from pydantic import Field

from .base import CLIModel


class Amount(CLIModel):
    """Monetary amount with currency.

    Used for prices, totals, and other currency values.
    """

    value: float = Field(frozen=True)
    currency: str = Field(default="USD", frozen=True)
