"""`discover <site>`: run one site's CLI and write its envelope.

The decision table, in order. No step involves judgment; every outcome is a
fixed function of config.json and the site CLI's exit codes:

1. unknown site                              -> ConfigError (no envelope)
1b. disabled: true                            -> ConfigError (no envelope)
2. account: false                            -> no_account
3. cli: null                                 -> no_cli
4. `<cli> auth status` exit 0                -> continue
   exit 2                                    -> run auth_command once, re-check;
                                                still 2 -> auth_failed
   any other exit                            -> error
5. `<cli> tasks list --limit <TASKS_LIST_LIMIT>` exit 0 + JSON list -> ok
   (raw list untouched)
   non-zero exit, non-JSON, non-list         -> error
   non-finite number anywhere in the JSON    -> error
   timeout / missing executable (any step)   -> error
6. write + validate `<run>/<site>.json`

`tasks` is `[]` for every status but `ok`. Nothing is ever fabricated.

The stdout parse is strict (`jsonio.loads`), so `NaN` or `Infinity` from a site
CLI is an `error` envelope naming the literal. Python's default decoder accepts
both, and if they get through, the file this step writes is one no strict JSON
reader can parse -- while `microworker validate` still calls it valid -- and a
NaN price binds to SQLite as SQL NULL, so a priced task reads as unpriced.
"""

from __future__ import annotations

import json
import shlex

from cli_tools_shared.exceptions import ConfigError

from . import envelope, jsonio, paths, runner, sites
from .runner import RunnerError
from .sites import SiteConfig

# Every roster site's `tasks list` accepts `--limit` (cli-tools list
# contract). Discovery always asks for the full catalog up to this cap: the
# site CLIs default to small first-page limits (microworkers returns 100 rows
# per /jobs.php page and stops at its default of 100), which silently
# truncated the envelope to one page. Verified live 2026-09-04: microworkers
# held ~1600 available tasks while discovery captured exactly 100. 1000 covers
# every site's observed real queue; raising it later is one constant.
TASKS_LIST_LIMIT = 1000


def discover(site_name: str, run_id: str, timeout: int) -> dict:
    site = sites.get_site(site_name)
    if site.disabled:
        raise ConfigError(
            f"site '{site_name}' is disabled in config.json (disabled: true); "
            "discovery skips disabled sites -- no envelope is written")
    data = _discover(site, timeout)
    path = paths.envelope_path(run_id, site_name)
    envelope.write(path, data)
    return {
        "site": site_name,
        "status": data["status"],
        "path": str(path),
        "task_count": len(data["tasks"]),
    }


def _discover(site: SiteConfig, timeout: int) -> dict:
    if not site.account:
        return envelope.build(
            site.name, envelope.NO_ACCOUNT,
            "config.json marks this site account=false", [])
    if site.cli is None:
        return envelope.build(
            site.name, envelope.NO_CLI,
            "config.json marks this site cli=null", [])
    try:
        auth_failure = _ensure_authenticated(site, timeout)
        if auth_failure is not None:
            status, error = auth_failure
            return envelope.build(site.name, status, error, [])
        return _list_tasks(site, timeout)
    except RunnerError as exc:
        return envelope.build(site.name, envelope.ERROR, str(exc), [])


def _auth_status(site: SiteConfig, timeout: int) -> runner.RunResult:
    return runner.run([site.cli, "auth", "status"], timeout)


def _ensure_authenticated(site: SiteConfig, timeout: int):
    """None when authenticated, else the (status, error) to record."""
    check = _auth_status(site, timeout)
    if check.returncode == 0:
        return None
    if check.returncode != 2:
        return envelope.ERROR, _exit_message(check)
    if site.auth_command is None:
        return envelope.AUTH_FAILED, (
            f"`{site.cli} auth status` exited 2 and config.json has "
            "auth_command=null, so no login was attempted")
    login = runner.run(shlex.split(site.auth_command), timeout)
    recheck = _auth_status(site, timeout)
    if recheck.returncode == 0:
        return None
    if recheck.returncode == 2:
        return envelope.AUTH_FAILED, (
            f"`{site.auth_command}` exited {login.returncode} and "
            f"`{site.cli} auth status` still exits 2: {login.stderr.strip()}")
    return envelope.ERROR, _exit_message(recheck)


def _list_tasks(site: SiteConfig, timeout: int) -> dict:
    result = runner.run(
        [site.cli, "tasks", "list", "--limit", str(TASKS_LIST_LIMIT)], timeout)
    if result.returncode != 0:
        return envelope.build(site.name, envelope.ERROR, _exit_message(result), [])
    try:
        payload = jsonio.loads(result.stdout, f"`{site.cli} tasks list` stdout")
    except json.JSONDecodeError as exc:
        return envelope.build(
            site.name, envelope.ERROR,
            f"`{site.cli} tasks list` stdout is not JSON: {exc}", [])
    except jsonio.NonFiniteNumberError as exc:
        return envelope.build(
            site.name, envelope.ERROR,
            f"`{site.cli} tasks list` printed a non-finite number: {exc}", [])
    if not isinstance(payload, list):
        return envelope.build(
            site.name, envelope.ERROR,
            f"`{site.cli} tasks list` printed a JSON {type(payload).__name__}, "
            "expected a list", [])
    return envelope.build(site.name, envelope.OK, None, payload)


def _exit_message(result: runner.RunResult) -> str:
    return (f"`{' '.join(result.argv)}` exited {result.returncode}: "
            f"{result.stderr.strip()}")
