"""Fixed adam-server deploy targets for the legoscout display page.

Every path and port here is a real, already-reserved fact about adam-server,
not a default meant to be overridden -- there is exactly one deployment
target. `LEGOSCOUT_PORT` was picked at 8788 because 8787 (legoscout's own
local default) is already bound on this same Tailscale IP by Hermes' own web
UI dashboard; `release.check_port_free()` reverifies this on every deploy
instead of trusting this comment to stay true.
"""
from __future__ import annotations

from ..paths import MINIFIG_CROP_ROOT

REMOTE_HOST = "adam-server"
REMOTE_APP_ROOT = "/Users/adam/GitRepos/legoscout"
REMOTE_RELEASES = f"{REMOTE_APP_ROOT}/releases"
REMOTE_CURRENT = f"{REMOTE_APP_ROOT}/current"
REMOTE_SHARED_DIR = f"{REMOTE_APP_ROOT}/shared"
REMOTE_SHARED_DB = f"{REMOTE_SHARED_DIR}/found_deals.db"
REMOTE_SHARED_CROPS = f"{REMOTE_SHARED_DIR}/minifig-crops"

PM2_BIN = "/Users/adam/.hermes/node/bin/pm2"
UV_BIN = "/opt/homebrew/bin/uv"
KEEP_RELEASES = 5
PM2_APP_NAME = "legoscout-display"

# Where legoscout's code actually lives -- a subtree of the cli-tools
# monorepo, not this LegoScout project directory. `git archive` runs from
# here, scoped to just these two paths; `cli-tools-shared` has no local path
# dependencies of its own, so the two subtrees are the complete payload.
CLI_TOOLS_REPO = "/Users/adam/Dropbox/GitRepos/cli-tools"
LEGOSCOUT_SUBTREE = "_personal/legoscout"
SHARED_SUBTREE = "_repo/cli-tools-shared"

# This LegoScout project's working ledger and mutable, content-addressed crop
# cache. Both live outside release directories and survive code promotion.
LOCAL_DB = "/Users/adam/Dropbox/GitRepos/Agents/LegoScout/data/found_deals.db"
LOCAL_SHARED_CROPS = MINIFIG_CROP_ROOT

# The fixed uv tool venv `uv tool install --editable ... --force` reinstalls
# into on every deploy. Fixed name means this path survives every release;
# pm2's ecosystem file points at it directly.
REMOTE_TOOL_PYTHON = "/Users/adam/.local/share/uv/tools/legoscout-cli/bin/python"

LEGOSCOUT_HOST = "100.117.198.37"
LEGOSCOUT_PORT = 8788
LEGOSCOUT_URL = f"http://{LEGOSCOUT_HOST}:{LEGOSCOUT_PORT}/"
REACHABLE_TIMEOUT_SECONDS = 60
