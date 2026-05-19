"""Data Table models for n8n's built-in database feature."""
from typing import List, Optional

from .base import CLIModel


class DataTableColumn(CLIModel):
    """A column in a data table."""
    id: str = ""
    name: str
    type: str  # "string", "number", "boolean", "date"
    index: Optional[int] = None


class DataTable(CLIModel):
    """A data table in an n8n project."""
    id: str
    name: str
    columns: List[DataTableColumn] = []
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
