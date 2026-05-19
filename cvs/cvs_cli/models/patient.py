"""Patient models for CVS CLI."""
from typing import Any, Dict, List, Optional

from .base import CLIModel


class Patient(CLIModel):
    """Patient model from the CVS API."""

    id: Optional[str] = None
    idType: Optional[str] = None
    memberType: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    dateOfBirth: Optional[str] = None
    gender: Optional[str] = None
    addresses: Optional[List[Dict[str, Any]]] = None
