"""Course models for Udemy Instructor API responses."""
from typing import Any, Optional

from pydantic import ConfigDict, Field
from .base import CLIModel


class Course(CLIModel):
    """Udemy course returned by the taught courses endpoint."""

    model_config = ConfigDict(
        extra="allow",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    id: str = Field(frozen=True)
    title: str
    url: str
    created: Optional[str] = None
    description: Optional[str] = None
    headline: Optional[str] = None
    is_paid: Optional[bool] = None
    is_published: Optional[bool] = None
    num_reviews: Optional[int] = None
    published_time: Optional[str] = None
    published_title: Optional[str] = None
    rating: Optional[float] = None
    visible_instructors: Optional[list[dict[str, Any]]] = None


def create_course(data: dict) -> Course:
    """Create a Course model from Udemy API response data."""
    return Course(**data)
