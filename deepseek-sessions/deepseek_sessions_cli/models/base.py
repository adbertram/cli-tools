"""Base model for DeepSeekSessions CLI.

All models inherit from CLIModel which provides:
- JSON serialization showing all fields (including None values)
- Whitespace stripping for string fields
- Populate by field name (allows both alias and field name)
"""
from pydantic import BaseModel, ConfigDict


class CLIModel(BaseModel):
    """Base model with CLI-friendly configuration.

    Features:
    - extra="ignore": Unknown fields are silently ignored
    - str_strip_whitespace: Leading/trailing whitespace stripped from strings
    - populate_by_name: Allows using either alias or field name
    """

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    def to_dict(self, exclude_none: bool = False) -> dict:
        """Convert model to dict for JSON output."""
        return self.model_dump(exclude_none=exclude_none)
