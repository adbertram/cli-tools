"""Read-only access to the Hermes Agent SQLite state store.

The store is opened through a `mode=ro` URI so this CLI can never write to it,
even by accident. Hermes runs the same database in WAL mode with one writer and
many readers, so a read-only connection is safe while Hermes is live.
"""
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError

from .parsers import (
    SKILL_TOOLS,
    casefold_key,
    parse_tool_calls,
    slash_command_name,
    tool_status,
    workspace_key,
)

activity = get_activity_logger("hermes-sessions")


def _skill_hits(role: Optional[str], content: Optional[str], tool_calls: Optional[str]) -> int:
    """How many skill records one message contributes.

    Mirrors the rules in `HermesSessionsClient._session_skills` exactly so a
    SQL-side count can never disagree with the rows `skills list` returns.
    """
    hits = 0
    if role == "user" and slash_command_name(content):
        hits += 1
    hits += sum(1 for call in parse_tool_calls(tool_calls) if call["name"] in SKILL_TOOLS)
    return hits


# Deterministic SQL helpers registered on every connection. They let bounded
# aggregate queries use the same Python semantics the row builders use, instead
# of re-implementing them in SQL where `lower()` is ASCII-only and a
# whitespace-only `cwd` is not NULL.
SQL_FUNCTIONS = {
    "hs_casefold": (1, casefold_key),
    "hs_workspace": (1, workspace_key),
    "hs_tool_status": (1, tool_status),
    "hs_skill_hits": (3, _skill_hits),
}


class StateStore:
    """A read-only connection to `state.db`."""

    def __init__(self, path: Path):
        self.path = path
        self._connection: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """Open (once) and return the read-only connection."""
        if self._connection is not None:
            return self._connection

        if not self.path.is_file():
            raise ClientError(
                f"Hermes state store not found at {self.path}. Set "
                "HERMES_SESSIONS_HERMES_HOME or HERMES_HOME to the Hermes home directory."
            )
        try:
            connection = sqlite3.connect(
                f"file:{self.path}?mode=ro", uri=True, timeout=10.0
            )
        except sqlite3.Error as exc:
            raise ClientError(f"Cannot open Hermes state store {self.path}: {exc}")
        connection.row_factory = sqlite3.Row
        for name, (arity, func) in SQL_FUNCTIONS.items():
            connection.create_function(name, arity, func, deterministic=True)
        self._connection = connection
        activity.info("Opened Hermes state store: %s", self.path)
        return connection

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        """Run a read query and return plain dict rows."""
        return list(self.iter_query(sql, params))

    def iter_query(self, sql: str, params: Sequence[Any] = ()) -> Iterator[Dict[str, Any]]:
        """Stream a read query so large scans never materialize at once."""
        connection = self.connect()
        operation = next(iter(sql.split()), "UNKNOWN").upper()
        activity.info("Hermes state query: %s", operation)
        try:
            cursor = connection.execute(sql, tuple(params))
        except sqlite3.DatabaseError as exc:
            raise ClientError(f"Hermes state query failed: {exc}")
        try:
            for row in cursor:
                yield dict(row)
        except sqlite3.DatabaseError as exc:
            raise ClientError(f"Hermes state query failed: {exc}")
        finally:
            cursor.close()

    def has_table(self, name: str) -> bool:
        """Whether the store carries a table or view with this name."""
        rows = self.query(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        )
        return bool(rows)

    def columns(self, table: str) -> List[str]:
        """Column names of a table, or an empty list when it does not exist."""
        if not self.has_table(table):
            return []
        return [row["name"] for row in self.query(f"PRAGMA table_info({table})")]

    def close(self) -> None:
        """Close the connection if it was opened."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
