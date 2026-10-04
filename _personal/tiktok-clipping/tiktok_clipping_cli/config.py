"""Lifecycle metadata. Trusted operational configuration is validated by safety.py."""


class Config:
    """Declare that this coordinator owns no reusable remote credentials."""
    DIST_NAME = "tiktok-clipping-cli"
    CREDENTIAL_TYPES = []
