"""Order models for CVS CLI."""
from typing import Optional

from .base import CLIModel


class Order(CLIModel):
    """Order model from the CVS API."""

    orderId: Optional[str] = None
    orderDate: Optional[str] = None
    orderStatus: Optional[str] = None
    drugName: Optional[str] = None
    patientFirstName: Optional[str] = None
    storeNumber: Optional[str] = None
    fulfillmentType: Optional[str] = None
    cost: Optional[float] = None
    pickupLocation: Optional[str] = None
