#!/usr/bin/env bash
# Build MacSpeech.app — compile the Swift helper, assemble the .app bundle, and
# ad-hoc codesign it. The .app MUST live at the tool's REAL profile path because
# the Speech Recognition TCC grant is path-specific for ad-hoc-signed apps.
#
# Usage:
#   build-app.sh [install-dir]
#
#   install-dir  Directory to assemble MacSpeech.app into.
#                Default: ~/.local/share/cli-tools/macspeech
#
# Produces: <install-dir>/MacSpeech.app/Contents/{MacOS/macspeech-helper, Info.plist}
#
# Fail-fast: any compile/assemble/sign error aborts with a non-zero exit.
set -euo pipefail

log() { printf '[build-app] %s\n' "$*" >&2; }
fail() { printf '[build-app] ERROR: %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWIFT_SRC="$SCRIPT_DIR/macspeech_helper.swift"
INFO_PLIST="$SCRIPT_DIR/AppInfo.plist"

INSTALL_DIR="${1:-$HOME/.local/share/cli-tools/macspeech}"
APP_DIR="$INSTALL_DIR/MacSpeech.app"
MACOS_DIR="$APP_DIR/Contents/MacOS"
HELPER_BIN="$MACOS_DIR/macspeech-helper"

[ -f "$SWIFT_SRC" ] || fail "Swift source not found: $SWIFT_SRC"
[ -f "$INFO_PLIST" ] || fail "Info.plist not found: $INFO_PLIST"
command -v swiftc >/dev/null 2>&1 || fail "swiftc not found (install Xcode command line tools: xcode-select --install)"
command -v codesign >/dev/null 2>&1 || fail "codesign not found"

log "Assembling app bundle at: $APP_DIR"
# Start clean so a stale binary can never linger inside the bundle.
rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR"

log "Compiling Swift helper -> $HELPER_BIN"
swiftc "$SWIFT_SRC" -O -o "$HELPER_BIN" -framework Speech -framework Foundation

log "Installing Info.plist (with NSSpeechRecognitionUsageDescription)"
cp "$INFO_PLIST" "$APP_DIR/Contents/Info.plist"

log "Ad-hoc codesigning the .app"
codesign --force --deep --sign - "$APP_DIR"

# Verify the binary exists and the signature is valid.
[ -x "$HELPER_BIN" ] || fail "helper binary missing or not executable after build: $HELPER_BIN"
codesign --verify --deep --strict "$APP_DIR" || fail "codesign verification failed for $APP_DIR"

log "Build complete: $APP_DIR"
printf '%s\n' "$APP_DIR"
