"""Shared helper functions for command modules."""
from pydantic import BaseModel


def model_to_dict(item):
    """Convert model or dict to dict for output."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item
