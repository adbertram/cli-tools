"""Base Pydantic model for DoorDash CLI."""
from pydantic import BaseModel, ConfigDict


class CLIModel(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        populate_by_name=True,
    )
