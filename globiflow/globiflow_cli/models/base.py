"""Base model configuration for CLI entities."""
from pydantic import BaseModel, ConfigDict


class CLIModel(BaseModel):
    """Base model with CLI-friendly configuration.

    Features:
    - Ignores unknown fields (useful when scraping may return extra data)
    - Strips whitespace from strings (cleans scraped content)
    - Serializes by field name (not alias) for consistent JSON output
    """
    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    def to_dict(self, exclude_none: bool = False) -> dict:
        """Convert model to dictionary for JSON output.

        Args:
            exclude_none: If True, omit fields with None values from output.
                          Defaults to False to show all model fields.

        Returns:
            Dictionary representation of the model.
        """
        return self.model_dump(exclude_none=exclude_none)
