"""Credential type definitions, validation, and masking."""

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class _CredentialConfig:
    """All properties for a single credential type, defined in one place."""

    required_fields: tuple = ()
    all_fields: tuple = ()
    login_prompts: tuple = ()       # (field_name, prompt_text, hide_input) tuples
    ephemeral_fields: tuple = ()
    sensitive_fields: tuple = ()


# Single source of truth: each credential type's full definition lives here.
# Adding a new type = one entry. No other locations to update.
_CONFIGS = {
    "api_key": _CredentialConfig(
        required_fields=("API_KEY",),
        all_fields=("API_KEY", "BASE_URL"),
        login_prompts=(("API_KEY", "API key", True),),
        sensitive_fields=("API_KEY",),
    ),
    "personal_access_token": _CredentialConfig(
        required_fields=("PERSONAL_ACCESS_TOKEN",),
        all_fields=("PERSONAL_ACCESS_TOKEN", "BASE_URL"),
        login_prompts=(("PERSONAL_ACCESS_TOKEN", "Personal access token", True),),
        sensitive_fields=("PERSONAL_ACCESS_TOKEN",),
    ),
    "oauth": _CredentialConfig(
        required_fields=("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN"),
        all_fields=(
            "CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN",
            "REFRESH_TOKEN", "TOKEN_EXPIRES_AT", "BASE_URL",
        ),
        login_prompts=(
            ("CLIENT_ID", "Client ID", False),
            ("CLIENT_SECRET", "Client secret", True),
        ),
        ephemeral_fields=("ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN_EXPIRES_AT"),
        sensitive_fields=("CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN"),
    ),
    "oauth_authorization_code": _CredentialConfig(
        required_fields=("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN"),
        all_fields=(
            "CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN",
            "REFRESH_TOKEN", "TOKEN_EXPIRES_AT", "REDIRECT_URI", "BASE_URL",
        ),
        login_prompts=(
            ("CLIENT_ID", "Client ID", False),
            ("CLIENT_SECRET", "Client secret", True),
            ("REDIRECT_URI", "Redirect URI", False),
        ),
        ephemeral_fields=("ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN_EXPIRES_AT"),
        sensitive_fields=("CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN"),
    ),
    "username_password": _CredentialConfig(
        required_fields=("USERNAME", "PASSWORD"),
        all_fields=("USERNAME", "PASSWORD", "BASE_URL"),
        login_prompts=(
            ("USERNAME", "Username", False),
            ("PASSWORD", "Password", True),
        ),
        sensitive_fields=("PASSWORD",),
    ),
    "browser_session": _CredentialConfig(
        all_fields=("BASE_URL",),
    ),
    "custom": _CredentialConfig(),
    "no_auth": _CredentialConfig(),
}

_EMPTY = _CredentialConfig()


class CredentialType(Enum):
    """Types of authentication credentials supported by CLI tools."""

    API_KEY = "api_key"
    PERSONAL_ACCESS_TOKEN = "personal_access_token"
    OAUTH = "oauth"
    OAUTH_AUTHORIZATION_CODE = "oauth_authorization_code"
    USERNAME_PASSWORD = "username_password"
    BROWSER_SESSION = "browser_session"
    CUSTOM = "custom"
    NO_AUTH = "no_auth"

    @property
    def _config(self) -> _CredentialConfig:
        return _CONFIGS.get(self.value, _EMPTY)

    @property
    def required_fields(self) -> list:
        """Fields that must be set for credentials to be valid."""
        return list(self._config.required_fields)

    @property
    def all_fields(self) -> list:
        """All fields associated with this credential type (for clearing)."""
        return list(self._config.all_fields)

    @property
    def login_prompts(self) -> list:
        """Return (field_name, prompt_text, hide_input) tuples for interactive login.

        For OAUTH_AUTHORIZATION_CODE, these are the setup prompts for app credentials.
        The actual token acquisition happens via a login_handler callback (browser flow).
        """
        return list(self._config.login_prompts)

    @property
    def ephemeral_fields(self) -> list:
        """Fields cleared on --force (tokens, transient auth state).

        Static credentials (API keys, PATs, client IDs, passwords) are never
        cleared by --force since they don't expire or change.
        """
        return list(self._config.ephemeral_fields)

    @property
    def sensitive_fields(self) -> list:
        """Fields that should be masked in status output."""
        return list(self._config.sensitive_fields)


def mask_value(value: str) -> str:
    """Mask a credential value for display.

    Shows first 4 and last 4 characters for long values.

    Args:
        value: The credential value to mask.

    Returns:
        Masked string like 'abc1...xyz4' or '***' for short values.
    """
    if not value or len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _combine_fields(cred_types: list, prop: str, custom_attr: str, config=None, key_fn=None) -> list:
    """Generic deduplication of credential fields across multiple types.

    Args:
        cred_types: List of CredentialType values.
        prop: Property name on CredentialType (e.g. 'required_fields').
        custom_attr: Config attribute for CUSTOM type (e.g. 'CUSTOM_REQUIRED_FIELDS').
        config: Config instance (needed for CUSTOM type).
        key_fn: Optional function to extract dedup key from item (default: item itself).
    """
    seen = set()
    result = []
    for ct in cred_types:
        if ct == CredentialType.CUSTOM and config is not None:
            items = getattr(config, custom_attr)
        else:
            items = getattr(ct, prop)
        for item in items:
            key = key_fn(item) if key_fn else item
            if key not in seen:
                seen.add(key)
                result.append(item)
    return result


def combined_required_fields(cred_types: list, config=None) -> list:
    """Deduplicated required fields across multiple credential types."""
    return _combine_fields(cred_types, "required_fields", "CUSTOM_REQUIRED_FIELDS", config)


def combined_all_fields(cred_types: list, config=None) -> list:
    """Deduplicated all fields across multiple credential types."""
    return _combine_fields(cred_types, "all_fields", "CUSTOM_ALL_FIELDS", config)


def combined_login_prompts(cred_types: list, config=None) -> list:
    """Deduplicated login prompts across multiple credential types (by field_name)."""
    return _combine_fields(cred_types, "login_prompts", "CUSTOM_LOGIN_PROMPTS", config, key_fn=lambda p: p[0])


def combined_ephemeral_fields(cred_types: list, config=None) -> list:
    """Deduplicated ephemeral fields across multiple credential types."""
    return _combine_fields(cred_types, "ephemeral_fields", "CUSTOM_EPHEMERAL_FIELDS", config)


def combined_sensitive_fields(cred_types: list, config=None) -> list:
    """Deduplicated sensitive fields across multiple credential types."""
    return _combine_fields(cred_types, "sensitive_fields", "CUSTOM_SENSITIVE_FIELDS", config)
