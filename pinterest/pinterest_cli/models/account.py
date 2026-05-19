"""Pinterest account models."""

from enum import Enum
from typing import Optional

from .base import CLIModel


class AccountType(str, Enum):
    """Pinterest user account types."""

    PINNER = "PINNER"
    BUSINESS = "BUSINESS"


class UserAccount(CLIModel):
    """Pinterest user account details."""

    id: str
    username: str
    account_type: Optional[AccountType] = None
    about: Optional[str] = None
    board_count: Optional[int] = None
    business_name: Optional[str] = None
    follower_count: Optional[int] = None
    following_count: Optional[int] = None
    monthly_views: Optional[int] = None
    pin_count: Optional[int] = None
    profile_image: Optional[str] = None
    website_url: Optional[str] = None
