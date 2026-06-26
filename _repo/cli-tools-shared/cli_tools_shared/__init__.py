"""Shared utilities for CLI tools: auth, profiles, config, output, OAuth, browser."""

from .config import BaseConfig, resolve_tool_dir, read_cli_tool_secret
from .paths import (
    resolve_config_dir,
    resolve_cache_dir,
    resolve_state_dir,
    config_dir_env_var,
    cache_dir_env_var,
    state_dir_env_var,
)
from .filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    apply_limit,
    get_nested_value,
    validate_filters,
    parse_filter_string,
)
from .filter_map import FilterMap
from .bulk import BulkProcessor
from .models import AIInstruction, CLIModel
from .credentials import (
    CredentialType,
    mask_value,
    combined_required_fields,
    combined_all_fields,
    combined_login_prompts,
    combined_sensitive_fields,
)
from .exceptions import ClientError, ConfigError, CredentialError
from .http_session import (
    BrowserAuthState,
    BrowserAuthStateError,
    BrowserAuthenticatedHttpClient,
    BrowserCookie,
    DEFAULT_BROWSER_HEADERS,
    DEFAULT_REQUESTS_BASE_DELAY,
    DEFAULT_REQUESTS_JITTER,
    DEFAULT_REQUESTS_MAX_DELAY,
    DEFAULT_REQUESTS_MAX_RETRIES,
    DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES,
    RequestsRetryPolicy,
    request_with_retry,
)
from .auth_commands import create_auth_app
from .cache_commands import create_cache_app
from .command_registry import register_commands
from .oauth import oauth_login, extract_code_from_input, generate_pkce_pair, build_token_auth_headers, parse_and_save_tokens
from .token_manager import TokenManager
from .app_factory import create_app, run_app
from .activity_log import get_activity_logger
from .repo_paths import find_cli_tools_repo_root, secret_manager_script
from .output import (
    print_json,
    print_table,
    print_output,
    print_error,
    print_warning,
    print_success,
    print_info,
    handle_error,
    confirm_destructive_action,
    print_ai_instruction,
    safe_symbol,
)


def __getattr__(name):
    """Lazy-load browser modules to avoid importing browser-harness at package import time."""
    if name in (
        "BrowserAutomation",
        "BrowserAutomationError",
        "AuthResult",
        "WebwrightBrowserAutomation",
    ):
        from .auth import (
            AuthResult,
            BrowserAutomation,
            BrowserAutomationError,
            WebwrightBrowserAutomation,
        )
        _browser_exports = {
            "BrowserAutomation": BrowserAutomation,
            "BrowserAutomationError": BrowserAutomationError,
            "AuthResult": AuthResult,
            "WebwrightBrowserAutomation": WebwrightBrowserAutomation,
        }
        return _browser_exports[name]
    if name in ("WebwrightBrowserService", "WebwrightServiceError"):
        from .browser.webwright import WebwrightBrowserService, WebwrightServiceError
        _webwright_exports = {
            "WebwrightBrowserService": WebwrightBrowserService,
            "WebwrightServiceError": WebwrightServiceError,
        }
        return _webwright_exports[name]
    if name == "create_profiles_app":
        from .profiles_commands import create_profiles_app
        return create_profiles_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # App factory
    "create_app",
    "run_app",
    # Filters
    "FilterValidationError",
    "apply_filters",
    "apply_properties_filter",
    "apply_limit",
    "get_nested_value",
    "validate_filters",
    "parse_filter_string",
    # Filter Map
    "FilterMap",
    # Bulk
    "BulkProcessor",
    # Models
    "AIInstruction",
    "CLIModel",
    # Config
    "BaseConfig",
    "resolve_tool_dir",
    # Paths
    "resolve_config_dir",
    "resolve_cache_dir",
    "resolve_state_dir",
    "config_dir_env_var",
    "cache_dir_env_var",
    "state_dir_env_var",
    # Secrets
    "read_cli_tool_secret",
    "AuthResult",
    "BrowserAutomation",
    "BrowserAutomationError",
    "WebwrightBrowserAutomation",
    "WebwrightBrowserService",
    "WebwrightServiceError",
    "CredentialType",
    "mask_value",
    "combined_required_fields",
    "combined_all_fields",
    "combined_login_prompts",
    "combined_sensitive_fields",
    "ClientError",
    "ConfigError",
    "CredentialError",
    "BrowserAuthState",
    "BrowserAuthStateError",
    "BrowserAuthenticatedHttpClient",
    "BrowserCookie",
    "DEFAULT_BROWSER_HEADERS",
    "RequestsRetryPolicy",
    "request_with_retry",
    "DEFAULT_REQUESTS_MAX_RETRIES",
    "DEFAULT_REQUESTS_BASE_DELAY",
    "DEFAULT_REQUESTS_MAX_DELAY",
    "DEFAULT_REQUESTS_JITTER",
    "DEFAULT_REQUESTS_RETRYABLE_STATUS_CODES",
    "create_auth_app",
    "create_cache_app",
    "create_profiles_app",
    "register_commands",
    "oauth_login",
    "extract_code_from_input",
    "generate_pkce_pair",
    "build_token_auth_headers",
    "parse_and_save_tokens",
    "TokenManager",
    # Activity Logging
    "get_activity_logger",
    "print_json",
    "print_table",
    "print_output",
    "print_error",
    "print_warning",
    "print_success",
    "print_info",
    "handle_error",
    "confirm_destructive_action",
    "print_ai_instruction",
    "safe_symbol",
]
