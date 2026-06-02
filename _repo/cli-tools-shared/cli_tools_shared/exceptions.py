"""Base exception classes for CLI tools."""


class ClientError(Exception):
    """Base exception for API/service client errors."""
    pass


class CredentialError(ClientError):
    """Exception for missing or invalid credentials."""
    pass


class ConfigError(Exception):
    """Exception for configuration and profile errors."""
    pass
