"""Configuration management for macspeech CLI.

macspeech wraps a locally compiled Swift helper (`macspeech-helper`) that runs
INSIDE a `MacSpeech.app` bundle. The bundle is installed at the tool's real
profile path because the macOS Speech Recognition TCC grant is path-specific for
ad-hoc-signed apps. There is no network service and no authentication.
"""

import os
from pathlib import Path
from typing import List, Optional

from cli_tools_shared.config import BaseConfig, get_tool_data_dir, resolve_tool_dir


# Default transcription timeout (seconds). Single source for the CLI option
# default, the client default, and the helper's internal watchdog.
DEFAULT_TIMEOUT = 300


class Config(BaseConfig):
    """Configuration manager for macspeech CLI."""

    DIST_NAME = "macspeech-cli"
    CREDENTIAL_TYPES: list = []  # no auth; on-device helper
    DEFAULT_BASE_URL = ""

    # The .app bundle name assembled by helper/build-app.sh.
    APP_BUNDLE_NAME = "MacSpeech.app"

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    @property
    def storage_dir(self) -> Path:
        """Profile-aware storage directory for runtime state."""
        return self.get_profile_data_dir()

    @property
    def install_dir(self) -> Path:
        """Directory holding MacSpeech.app.

        Defaults to the tool's real user-data root
        (~/.local/share/cli-tools/macspeech) — the SAME path helper/build-app.sh
        and install.sh assemble the .app into — because the Speech Recognition
        TCC grant is bound to this exact path for ad-hoc-signed apps.
        Overridable via MACSPEECH_INSTALL_DIR for tests/diagnostics.
        """
        override = os.getenv("MACSPEECH_INSTALL_DIR")
        if override:
            return Path(override).expanduser().resolve()
        # tool_name is the dist name without the "-cli" suffix (e.g. "macspeech").
        tool_name = self.DIST_NAME[:-4] if self.DIST_NAME.endswith("-cli") else self.DIST_NAME
        return get_tool_data_dir(tool_name).resolve()

    @property
    def app_path(self) -> Path:
        """Absolute path to MacSpeech.app."""
        return self.install_dir / self.APP_BUNDLE_NAME

    @property
    def helper_binary(self) -> Path:
        """Absolute path to the compiled helper inside the .app bundle."""
        return self.app_path / "Contents" / "MacOS" / "macspeech-helper"

    def is_app_installed(self) -> bool:
        """True if the .app bundle and its helper binary are present."""
        return self.app_path.is_dir() and self.helper_binary.is_file()

    @property
    def build_script(self) -> Path:
        """Path to the build script that assembles MacSpeech.app."""
        return Path(__file__).resolve().parent.parent / "helper" / "build-app.sh"

    @property
    def default_contextual_strings(self) -> List[str]:
        """Default contextual strings when --contextual-strings is omitted.

        Sourced from MACSPEECH_CONTEXTUAL_STRINGS (semicolon-separated phrases).
        Unset/empty by default; a later step may set a domain glossary.
        """
        return parse_contextual_strings(os.getenv("MACSPEECH_CONTEXTUAL_STRINGS"))

    def get_cli_version(self) -> Optional[str]:
        """No upstream binary version; report the helper presence instead."""
        return "installed" if self.is_app_installed() else None


def parse_contextual_strings(value: Optional[str]) -> List[str]:
    """Parse a semicolon-separated phrase list into a clean list.

    Empty/whitespace-only entries are dropped. None/empty input yields [].
    """
    if not value:
        return []
    return [phrase.strip() for phrase in value.split(";") if phrase.strip()]


# Language code -> SFSpeechRecognizer locale identifier.
# `en` maps to en-US; anything else passes through unchanged.
_LANGUAGE_LOCALE_OVERRIDES = {
    "en": "en-US",
}


def language_to_locale(language: str) -> str:
    """Map a CLI --language code to an SFSpeechRecognizer locale identifier."""
    return _LANGUAGE_LOCALE_OVERRIDES.get(language, language)


_config: Optional[Config] = None


def get_config(profile=None) -> Config:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
