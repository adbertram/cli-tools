"""Small shared constants for Bricklink commands."""
from enum import Enum


class RefundReason(str, Enum):
    CANCEL_ORDER = "Buyer and Seller agreed to cancel order"
    MISSING_UNSATISFACTORY = "Item was missing or unsatisfactory"


NOT_SHIPPED_STATUSES = {"PENDING", "UPDATED", "PROCESSING", "READY", "PAID", "PACKED"}
NOT_PICKED_STATUSES = {"PENDING", "UPDATED", "PROCESSING", "PAID"}


def is_shipped_status(status: str) -> bool:
    return status not in NOT_SHIPPED_STATUSES


def is_not_picked_status(status: str) -> bool:
    return status in NOT_PICKED_STATUSES
