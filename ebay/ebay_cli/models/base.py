"""Base model configuration for eBay CLI models."""
from pydantic import BaseModel, ConfigDict


class EbayBaseModel(BaseModel):
    """Base model with common configuration for all eBay models."""

    model_config = ConfigDict(
        # Allow population by field name or alias
        populate_by_name=True,
        # Validate on assignment
        validate_assignment=True,
        # Use enum values for serialization
        use_enum_values=True,
        # Extra fields are forbidden
        extra="ignore",
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary for JSON output."""
        return self.model_dump(exclude_none=True)
