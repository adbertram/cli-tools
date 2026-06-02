"""Facebook CLI models."""
import re
from typing import List, Optional

from pydantic import Field, field_validator

from cli_tools_shared import CLIModel

FACEBOOK_BASE_URL = "https://www.facebook.com"


class MarketplaceListing(CLIModel):
    """A Facebook Marketplace listing."""

    item_id: str = Field(frozen=True)
    title: str
    price: Optional[float] = None
    url: str
    location: Optional[str] = None
    description: Optional[str] = None
    image_urls: Optional[List[str]] = Field(default=None, exclude=True)
    local_images: Optional[List[str]] = None

    @field_validator("price", mode="before")
    @classmethod
    def normalize_price(cls, v):
        """Convert price string to float. '$10' -> 10.0, 'Free' -> 0.0."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            v = v.strip()
            if not v or v.lower() == "unknown":
                return None
            if v.lower() == "free":
                return 0.0
            cleaned = re.sub(r'[$,]', '', v)
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @field_validator("url", mode="before")
    @classmethod
    def make_absolute_url(cls, v):
        """Convert relative URL to absolute."""
        if isinstance(v, str) and v.startswith("/"):
            return f"{FACEBOOK_BASE_URL}{v}"
        return v


class Group(CLIModel):
    """A Facebook Group the user has joined."""

    group_id: str = Field(frozen=True)
    name: str
    url: Optional[str] = None
    member_count: Optional[str] = None


class Comment(CLIModel):
    """A comment on a Facebook Group post."""

    comment_id: Optional[str] = None
    author: str
    text: str
    created_time: Optional[str] = None
    replies: List["Comment"] = Field(default_factory=list)


class GroupPost(CLIModel):
    """A post from a Facebook Group."""

    post_id: str = Field(frozen=True)
    title: Optional[str] = None
    author: Optional[str] = None
    text: Optional[str] = None
    body: Optional[str] = None
    timestamp: Optional[str] = None
    url: Optional[str] = None
    thread_url: Optional[str] = None
    reactions: Optional[int] = None
    comment_count: Optional[int] = None
    comments: Optional[List[Comment]] = None
    image_urls: Optional[List[str]] = None


Comment.model_rebuild()
