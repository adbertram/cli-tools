"""10Web CLI models."""
from .base import CLIModel
from .ai_instruction import AIInstruction
from .website import (
    SubdomainCheckResult,
    Website,
    WebsiteDetail,
    create_subdomain_check_result,
    create_website,
    create_website_detail,
)

__all__ = [
    "AIInstruction",
    "CLIModel",
    "Website",
    "WebsiteDetail",
    "SubdomainCheckResult",
    "create_website",
    "create_website_detail",
    "create_subdomain_check_result",
]
