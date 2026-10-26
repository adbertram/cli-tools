"""Run the packaged local API engine with secrets passed only in the child environment."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from cli_tools_shared.config import read_cli_tool_secret
from cli_tools_shared.exceptions import ClientError
from .config import get_config

ENGINE = Path(__file__).parent / "engine"
PRODUCT_OPERATIONS = {"listGumroadProducts", "inspectGumroadProduct"}
BOOK_OPERATIONS = {"inspectGumroadBuild", "buildGumroadBook", "buildGumroadEpub"}


def run_operation(operation, payload, profile=None):
    node = shutil.which("node")
    if not node:
        raise ClientError("Node.js 22+ is required. Install Node.js, then reinstall gumroad.")
    runner = ENGINE / "dist" / "cli.js"
    if not runner.is_file() or not (ENGINE / "node_modules" / "@notionhq" / "client").is_dir():
        raise ClientError("Gumroad local engine is not installed. Run gumroad engine install.")
    env = os.environ.copy()
    env.pop("GUMROAD_ACCESS_TOKEN", None)
    env.pop("NOTION_API_TOKEN", None)
    if operation not in BOOK_OPERATIONS:
        token = get_config(profile).personal_access_token
        if not token:
            raise ClientError("Missing Gumroad access token. Run gumroad auth login.")
        env["GUMROAD_ACCESS_TOKEN"] = token
    if operation not in PRODUCT_OPERATIONS:
        token = read_cli_tool_secret("notion-api-token")
        if not token:
            raise ClientError("Missing CLI-tools secret notion-api-token. Authenticate the Notion CLI first.")
        env["NOTION_API_TOKEN"] = token
    # No automatic timeout/retry around possibly completed writes.
    result = subprocess.run(
        [node, str(runner)], input=json.dumps({"operation": operation, "input": payload}),
        text=True, stdout=subprocess.PIPE, env=env, cwd=ENGINE,
    )
    if result.returncode:
        raise ClientError("Gumroad operation failed. Inspect the preceding error; do not automatically repeat writes.")
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise ClientError("Local engine returned invalid JSON; completion unconfirmed. Do not retry writes.") from exc


def install_engine():
    """Explicit deterministic dependency installation from the committed npm lockfile."""
    npm = shutil.which("npm")
    if not npm:
        raise ClientError("npm and Node.js 22+ are required for the local engine.")
    for args in (["ci", "--include=dev"], ["run", "build"]):
        result = subprocess.run([npm, *args], cwd=ENGINE, stdout=2)
        if result.returncode:
            raise ClientError("Gumroad engine installation failed.")
    return {"installed": True, "engine": str(ENGINE)}
