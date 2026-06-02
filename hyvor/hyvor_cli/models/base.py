"""Base model for Hyvor CLI.

All models inherit from CLIModel which provides:
- JSON serialization showing all fields (including None values)
- Whitespace stripping for string fields
- Populate by field name (allows both alias and field name)

Read-Only Field Patterns (use in subclasses):
- Field(frozen=True): Immutable after model creation
- Field(exclude=True): Excluded from model_dump() output
- Field(init=False): Excluded from __init__ (requires default)
- Combine as needed: Field(frozen=True, exclude=True)

Example:
    class Item(CLIModel):
        id: str = Field(frozen=True)  # Server-assigned, immutable
        created_at: Optional[str] = Field(default=None, frozen=True)
"""
from pydantic import BaseModel, ConfigDict


class CLIModel(BaseModel):
    """Base model with CLI-friendly configuration.

    Features:
    - extra="ignore": Unknown fields are silently ignored
    - str_strip_whitespace: Leading/trailing whitespace stripped from strings
    - populate_by_name: Allows using either alias or field name

    Read-Only Fields (use Field() in subclasses):
    - frozen=True: Raises error if field is modified after creation
    - exclude=True: Omits field from model_dump() output
    - init=False: Excludes from __init__ (must have default value)
    """

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    def to_dict(self, exclude_none: bool = False) -> dict:
        """Convert model to dict for JSON output.

        Args:
            exclude_none: If True, omit None values from output.
                          Defaults to False to show all model fields.

        Returns:
            Dict representation of the model
        """
        return self.model_dump(exclude_none=exclude_none)
