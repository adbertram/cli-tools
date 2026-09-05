"""The board's FastAPI service: ledger views, board state, and the dispatcher.

Read/write split, stated once: the ledger (`data/tasks.db`) is opened here
read-only through `db.list_tasks()`/`db.get_task()` -- the same engine-enforced
`mode=ro` connection the CLI's query commands use -- while everything the
board owns (columns, approval flags, delegations, settings) lives in
`data/board.db` and is written only by this process. On adam-server the
ledger is a snapshot pushed from the discovery machine, so this service never
writes it by construction.

THE APPROVAL GATE LIVES HERE. A `work` delegation tells the agent to research
and recommend -- its prompt forbids applying -- and the card walks
`delegated` -> `working` (when the agent starts) -> `review` (when it
finishes). `approve` is the ONLY endpoint that creates an `apply`
delegation, and only from `review`. No other path can make an agent run an
apply, so Adam's board click is the single approval mechanism.

The dispatcher is one daemon thread: it claims `pending` delegations, runs
the configured harness command (a shell template whose `{prompt}` is
replaced by the rendered, shell-quoted prompt and whose `{site}`/`{task_id}`
name the card -- by default `claude -p --agent worker-<site>`, so the site's
own worker agent does the work), streams output to the delegation's log
file, and moves the card on completion. The agent itself moves its own card
too, via `microworker board state`, on the same schedule: `working` while it
works, `review` when done. `kill` kills the process group, which the monitor
thread then records as failed.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from string import Template
from typing import Optional

import uvicorn
from cli_tools_shared.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .. import db, jsonio, paths
from ..envelope import utc_now

STATIC_DIR = Path(__file__).parent / "static"

# How many lines of a delegation log the detail endpoint returns.
LOG_TAIL_LINES = 400
LOG_TAIL_BYTES = 64 * 1024

DEFAULT_SETTINGS: dict[str, str] = {
    # The shell command that runs the agent. `{prompt}` is replaced with the
    # rendered prompt, shell-quoted. `{prompt_file}` (the same text on disk)
    # is supported for harnesses that want a file argument instead.
    "harness_command": 'claude -p --agent worker-{site} "{prompt}"',
    "work_prompt": """You are a MicroWorker task agent on adam-server, working in the MicroWorker repo at $root. You were delegated this card by the board as the site's worker.

The task: $site / $task_id
Title: $title
Description: $description
URL: $url
Pay: $pay $currency | estimated $est minutes | $slots slots open | expires $expires

Contract as stored: $task_json

Get the live contract with `microworker tasks get $site $task_id` if you need more.

YOUR CARD ON THE BOARD: you own its status while you work.
- As soon as you begin working, run: microworker board state $site $task_id working
- When your work is finished, run: microworker board state $site $task_id review
- Open your final reply with the line: Board: $site $task_id review

Work the task far enough to produce a recommendation: verify it is real and still open on the site, assess pay vs estimated minutes, check requirements, and name anything that would block applying. Use the site's CLI for anything site-facing.

HARD RULES:
- Never apply to, accept, or submit proof for this task. Applying requires Adam's explicit approval on the board; it is not yours to give.
- Never drive a browser. All browser automation lives in the site CLIs.
- Evidence only: report what a CLI returned. No invented tasks, pay, or facts; unknown fields are null.

End your reply with a clear recommendation: WORK IT / SKIP / NEEDS INFO, and why. The board shows your reply to Adam in the Review column.""",
    "apply_prompt": """Adam APPROVED applying to this task on the board. You are the site's worker running the approved apply.

Task: $site / $task_id
Title: $title
Description: $description
URL: $url

YOUR CARD ON THE BOARD: while you work the apply, run: microworker board state $site $task_id working
Open your final reply with the line: Board: $site $task_id review

Run the site's CLI apply command for this exact task with its confirm flag -- that approval is given -- and report exactly what happened, quoting the CLI's output. The hard rules still bind you: never drive a browser, evidence only, and apply to no OTHER task.""",
    "refresh_seconds": "15",
    # The board's default view: show only tasks the task evaluator marked as
    # AI-capable (`ai_can_handle = 1`). Adam can uncheck the header toggle to
    # see the full ledger; the toggle persists this key back to board.db.
    "ai_only_filter": "true",
    # A second header toggle, off by default: when on, only AI-capable tasks
    # the evaluator marked multimodal (`multimodal_required = 1` -- the agent
    # must take image, video, or audio input) are shown. Persisted the same
    # way as `ai_only_filter`.
    "multimodal_only_filter": "false",
}

PROMPT_PLACEHOLDER = "{prompt}"


class MoveBody(BaseModel):
    site: str
    task_id: str
    column: str


class DelegateBody(BaseModel):
    site: str
    task_id: str
    prompt: Optional[str] = None


class ApproveBody(BaseModel):
    site: str
    task_id: str


class SettingsBody(BaseModel):
    settings: dict[str, str]


def _http_error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def _task_or_404(site: str, task_id: str) -> dict:
    try:
        return db.get_task(site, task_id)
    except ClientError as exc:
        raise _http_error(404, str(exc)) from exc


def _state_or_default(site: str, task_id: str, states: dict) -> dict:
    row = states.get((site, task_id))
    return {
        "column": row["column_id"] if row else "backlog",
        "approved": bool(row["approved"]) if row else False,
    }


def _delegation_summary(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "exit_code": row["exit_code"],
    }


def _move_card(site: str, task_id: str, column: str, now: str) -> None:
    """Move one card's column, preserving its approval flag (dispatcher use)."""
    states = {(row["site"], row["task_id"]): row for row in db.board_task_states()}
    approved = _state_or_default(site, task_id, states)["approved"]
    db.board_upsert_task_state(site, task_id, column, approved=approved,
                               updated_at=now)


def _board_snapshot() -> dict:
    """Columns plus one card per ledger task, board state merged in."""
    meta: dict = {"replica_error": None, "task_count": 0, "now": utc_now()}
    try:
        tasks = db.list_tasks()
    except ClientError as exc:
        tasks = []
        meta["replica_error"] = str(exc)
    states = {(row["site"], row["task_id"]): row for row in db.board_task_states()}
    latest = db.board_latest_delegations()
    cards = []
    for task in tasks:
        key = (task["site"], task["task_id"])
        state = _state_or_default(key[0], key[1], states)
        cards.append({
            "site": task["site"],
            "task_id": task["task_id"],
            "title": task["title"],
            "description": task["description"],
            "url": task["url"],
            "pay_amount": task["pay_amount"],
            "pay_currency": task["pay_currency"],
            "est_minutes": task["est_minutes"],
            "slots_open": task["slots_open"],
            "expires_at": task["expires_at"],
            "last_seen_at": task["last_seen_at"],
            "ai_can_handle": task["ai_can_handle"],
            "multimodal_required": task["multimodal_required"],
            "column": state["column"],
            "approved": state["approved"],
            "delegation": _delegation_summary(latest.get(key)),
        })
    meta["task_count"] = len(cards)
    replica = paths.db_path()
    if replica.is_file():
        meta["replica_mtime"] = replica.stat().st_mtime
    meta["settings"] = _settings()
    return {"columns": list(db.BOARD_COLUMNS), "cards": cards, "meta": meta}


def _settings() -> dict[str, str]:
    return {**DEFAULT_SETTINGS, **db.board_settings()}


def _prompt_mapping(task: dict) -> dict[str, str]:
    contract = {column: task.get(column)
                for column in db.CONTRACT_COLUMNS if column != "raw"}
    return {
        "site": task["site"],
        "task_id": task["task_id"],
        "title": task.get("title") or "(no title)",
        "description": task.get("description") or "(no description stored)",
        "url": task.get("url") or "(no url)",
        "pay": str(task.get("pay_amount")),
        "currency": task.get("pay_currency") or "",
        "est": str(task.get("est_minutes")),
        "slots": str(task.get("slots_open")),
        "expires": task.get("expires_at") or "(no expiry)",
        "task_json": jsonio.dumps(contract, ensure_ascii=False),
        "root": str(paths.project_root()),
    }


def _render_prompt(template: str, task: dict) -> str:
    return Template(template).substitute(_prompt_mapping(task))


class Dispatcher:
    """One daemon thread claiming `pending` delegations and running them."""

    POLL_SECONDS = 3

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._processes: dict[int, subprocess.Popen] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="board-dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            processes = list(self._processes.values())
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                for delegation in db.board_pending_delegations():
                    self._launch(delegation)
            except BaseException as exc:  # the loop must survive anything
                print(f"board-dispatcher: {exc!r}", flush=True)
            self._stop.wait(self.POLL_SECONDS)

    def _launch(self, delegation: dict) -> None:
        """Claim and run one delegation; its monitor thread finishes it."""
        log_path = paths.delegation_log_dir() / f"delegation-{delegation['id']}.log"
        try:
            task = db.get_task(delegation["site"], delegation["task_id"])
            settings = _settings()
            template = settings.get(
                f"{delegation['kind']}_prompt",
                DEFAULT_SETTINGS[f"{delegation['kind']}_prompt"])
            prompt = (delegation.get("prompt") or "").strip() \
                or _render_prompt(template, task)
            harness = settings.get("harness_command",
                                   DEFAULT_SETTINGS["harness_command"])
            if PROMPT_PLACEHOLDER not in harness:
                raise ValueError(
                    "harness_command must contain {prompt}; see Settings")
            prompt_file = log_path.with_suffix(".prompt.txt")
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            prompt_file.write_text(prompt)
            command = harness.replace(PROMPT_PLACEHOLDER, shlex.quote(prompt))
            command = command.replace("{site}", delegation["site"])
            command = command.replace("{task_id}", delegation["task_id"])
            command = command.replace(
                "{prompt_file}", shlex.quote(str(prompt_file)))
            log_file = open(log_path, "ab")
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=paths.project_root(),
                env={**os.environ, "MICROWORKER_ROOT": str(paths.project_root())},
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except BaseException as exc:
            _append_log(log_path, f"[dispatcher] launch failed: {exc!r}\n")
            db.board_update_delegation(
                delegation["id"], status="failed", finished_at=utc_now(),
                log_path=str(log_path))
            return
        now = utc_now()
        db.board_update_delegation(
            delegation["id"], status="running", pid=process.pid,
            started_at=now, log_path=str(log_path))
        # The agent is now working the card; the dispatcher flips it to
        # `working` the moment the process starts, and the agent itself does
        # the same via `microworker board state` (idempotent either way).
        _move_card(delegation["site"], delegation["task_id"], "working", now)
        with self._lock:
            self._processes[delegation["id"]] = process
        threading.Thread(
            target=self._monitor,
            args=(delegation["id"], process, log_file),
            name=f"delegation-{delegation['id']}",
            daemon=True).start()

    def _monitor(self, delegation_id: int, process: subprocess.Popen,
                 log_file) -> None:
        exit_code = process.wait()
        log_file.close()
        with self._lock:
            self._processes.pop(delegation_id, None)
        status = "done" if exit_code == 0 else "failed"
        now = utc_now()
        db.board_update_delegation(
            delegation_id, status=status, exit_code=exit_code,
            finished_at=now)
        delegation = db.board_get_delegation(delegation_id)
        states = {(row["site"], row["task_id"]): row
                  for row in db.board_task_states()}
        key = (delegation["site"], delegation["task_id"])
        state = states.get(key)
        approved = bool(state["approved"]) if state else False
        if delegation["kind"] == "work":
            # Done: the agent finished and the card awaits Adam's review.
            # Failed: back to the Delegated queue, visibly failed, so Adam
            # can re-delegate deliberately.
            column = "review" if status == "done" else "delegated"
            db.board_upsert_task_state(
                key[0], key[1], column, approved=approved, updated_at=now)
        elif delegation["kind"] == "apply":
            # Done: the apply landed; the card is finished. Failed: the
            # approval was consumed without a result, so it is withdrawn and
            # the card returns to Review for Adam to approve again.
            if status == "done":
                db.board_upsert_task_state(
                    key[0], key[1], "done", approved=True, updated_at=now)
            else:
                db.board_upsert_task_state(
                    key[0], key[1], "review", approved=False, updated_at=now)

    def kill(self, delegation: dict) -> None:
        """Kill a running delegation; its monitor records it failed."""
        with self._lock:
            process = self._processes.get(delegation["id"])
        if process is None:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


dispatcher = Dispatcher()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    dispatcher.start()
    yield
    dispatcher.stop()


app = FastAPI(title="MicroWorker board", lifespan=lifespan)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/static/sortable.min.js")
def sortable() -> FileResponse:
    return FileResponse(STATIC_DIR / "sortable.min.js",
                        media_type="application/javascript")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "now": utc_now()}


@app.get("/api/board")
def board() -> dict:
    return _board_snapshot()


@app.post("/api/cards/move")
def move_card(body: MoveBody) -> dict:
    _task_or_404(body.site, body.task_id)
    states = {(row["site"], row["task_id"]): row
              for row in db.board_task_states()}
    state = _state_or_default(body.site, body.task_id, states)
    try:
        db.board_upsert_task_state(
            body.site, body.task_id, body.column,
            approved=state["approved"], updated_at=utc_now())
    except ClientError as exc:
        raise _http_error(400, str(exc)) from exc
    return {"site": body.site, "task_id": body.task_id,
            "column": body.column, "approved": state["approved"]}


@app.post("/api/cards/delegate")
def delegate_card(body: DelegateBody) -> dict:
    _task_or_404(body.site, body.task_id)
    if db.board_active_delegation(body.site, body.task_id, "work"):
        raise _http_error(409, "this card already has an active work delegation")
    states = {(row["site"], row["task_id"]): row
              for row in db.board_task_states()}
    approved = _state_or_default(body.site, body.task_id, states)["approved"]
    now = utc_now()
    delegation_id = db.board_create_delegation(
        body.site, body.task_id, "work", body.prompt or "", "", now)
    db.board_upsert_task_state(
        body.site, body.task_id, "delegated", approved=approved, updated_at=now)
    return {"id": delegation_id, "kind": "work", "status": "pending",
            "created_at": now}


@app.post("/api/cards/approve")
def approve_card(body: ApproveBody) -> dict:
    _task_or_404(body.site, body.task_id)
    states = {(row["site"], row["task_id"]): row
              for row in db.board_task_states()}
    state = _state_or_default(body.site, body.task_id, states)
    if state["column"] != "review":
        raise _http_error(409, "only a card in the Review column can be approved")
    if state["approved"]:
        raise _http_error(409, "this card is already approved")
    if db.board_active_delegation(body.site, body.task_id, "apply"):
        raise _http_error(409, "this card already has an active apply delegation")
    now = utc_now()
    delegation_id = db.board_create_delegation(
        body.site, body.task_id, "apply", "", "", now)
    db.board_upsert_task_state(
        body.site, body.task_id, "review", approved=True, updated_at=now)
    return {"id": delegation_id, "kind": "apply", "status": "pending",
            "created_at": now}


@app.get("/api/cards/delegations")
def card_delegations(site: str, task_id: str) -> dict:
    """Every delegation for one card, oldest first, summarized."""
    rows = db.board_delegations(site, task_id)
    return {"delegations": [
        {key: row[key] for key in
         ("id", "site", "task_id", "kind", "status", "pid", "exit_code",
          "created_at", "started_at", "finished_at")}
        for row in rows]}


@app.post("/api/delegations/{delegation_id}/kill")
def kill_delegation(delegation_id: int) -> dict:
    try:
        delegation = db.board_get_delegation(delegation_id)
    except ClientError as exc:
        raise _http_error(404, str(exc)) from exc
    if delegation["status"] == "pending":
        db.board_update_delegation(
            delegation_id, status="failed", finished_at=utc_now())
    elif delegation["status"] == "running":
        dispatcher.kill(delegation)
    else:
        raise _http_error(409, f"delegation is already {delegation['status']}")
    return {"id": delegation_id, "killed": True}


@app.get("/api/delegations/{delegation_id}")
def delegation_detail(delegation_id: int) -> dict:
    try:
        delegation = db.board_get_delegation(delegation_id)
    except ClientError as exc:
        raise _http_error(404, str(exc)) from exc
    return {**delegation, "log_tail": _log_tail(delegation.get("log_path"))}


@app.get("/api/settings")
def get_settings() -> dict:
    return _settings()


@app.put("/api/settings")
def put_settings(body: SettingsBody) -> dict:
    db.board_set_settings(body.settings)
    return _settings()


def _append_log(log_path: Path, text: str) -> None:
    """Append a dispatcher-side note to a delegation's log file."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as handle:
            handle.write(text)
    except OSError:
        pass


def _log_tail(log_path: str | None) -> str:
    if not log_path:
        return ""
    path = Path(log_path)
    if not path.is_file():
        return ""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - LOG_TAIL_BYTES))
        if size > LOG_TAIL_BYTES:
            next(handle)  # drop the partial first line
        text = handle.read().decode("utf-8", errors="replace")
    lines = text.splitlines()
    return "\n".join(lines[-LOG_TAIL_LINES:])


def run(host: str, port: int) -> None:
    """Serve the board until interrupted. Called by `microworker board serve`."""
    uvicorn.run(app, host=host, port=port, log_level="info")
