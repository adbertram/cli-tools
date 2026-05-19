"""Small typed model base for Fitnesspal CLI."""
from copy import deepcopy
from typing import Any, get_type_hints


class CLIModel:
    """Simple annotation-backed container with JSON-friendly serialization."""

    def __init__(self, **data):
        fields = get_type_hints(type(self))
        for name in fields:
            if name in data:
                value = data[name]
            elif hasattr(type(self), name):
                value = deepcopy(getattr(type(self), name))
            else:
                raise TypeError(f"Missing required field: {name}")
            if isinstance(value, str):
                value = value.strip()
            setattr(self, name, value)

    def model_dump(self, exclude_none: bool = False) -> dict:
        """Convert model to dict for JSON output."""
        return {
            name: self._serialize(getattr(self, name), exclude_none)
            for name in get_type_hints(type(self))
            if not exclude_none or getattr(self, name) is not None
        }

    def to_dict(self, exclude_none: bool = False) -> dict:
        """Convert model to dict for JSON output."""
        return self.model_dump(exclude_none=exclude_none)

    @classmethod
    def _serialize(cls, value: Any, exclude_none: bool):
        if isinstance(value, CLIModel):
            return value.model_dump(exclude_none=exclude_none)
        if isinstance(value, list):
            return [
                cls._serialize(item, exclude_none)
                for item in value
                if not exclude_none or item is not None
            ]
        if isinstance(value, dict):
            return {
                key: cls._serialize(item, exclude_none)
                for key, item in value.items()
                if not exclude_none or item is not None
            }
        return value
