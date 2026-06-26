#!/usr/bin/env bash
# Install macspeech: install the Python launcher AND build the MacSpeech.app
# helper at the tool's real profile path.
#
# The MacSpeech.app helper is part of macspeech's implementation contract: the
# CLI cannot transcribe without it, and the Speech Recognition TCC grant is
# bound to the .app's exact install path. This script provisions both pieces.
#
# Usage: ./install.sh
set -euo pipefail

log() { printf '[install] %s\n' "$*" >&2; }
fail() { printf '[install] ERROR: %s\n' "$*" >&2; exit 1; }

TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v uv >/dev/null 2>&1 || fail "uv not found (https://docs.astral.sh/uv/)"

log "Installing macspeech launcher via uv"
uv tool install -e "$TOOL_DIR" --force --refresh

# Resolve the install dir from the Python config (single source of truth) so the
# .app is built at exactly the path the CLI looks for it at runtime. The Speech
# Recognition TCC grant is bound to this exact path, so the two MUST agree.
log "Resolving install dir from macspeech config"
INSTALL_DIR="$(uv run --project "$TOOL_DIR" python -c 'from macspeech_cli.config import get_config; print(get_config().install_dir)')"
[ -n "$INSTALL_DIR" ] || fail "could not resolve install dir from macspeech config"

log "Building MacSpeech.app helper at $INSTALL_DIR"
"$TOOL_DIR/helper/build-app.sh" "$INSTALL_DIR"

log "macspeech installed. First on-device transcription will prompt for"
log "Speech Recognition permission (one-time, per install path)."
