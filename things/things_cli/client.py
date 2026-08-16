"""Things 3 SQLite database client.

Direct SQLite access to the Things 3 database for read and write operations.
- Reads: Safe anytime (database uses WAL mode for concurrent reads)
- Writes: Only when Things.app is not running (to prevent corruption)
"""
import multiprocessing as mp
import os
import secrets
import sqlite3
import string
import subprocess
import sys
import time
from datetime import datetime, timedelta
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from .models import (
    Area,
    AuthStatus,
    ChecklistItem,
    Project,
    Tag,
    Task,
    TaskStatus,
    TaskType,
    StartType,
)


class ClientError(Exception):
    """Custom exception for Things client errors."""
    pass


class AppleScriptTimeoutError(ClientError):
    """Raised when osascript exceeds the bounded Things AppleScript timeout."""
    pass


class UnpersistedUpdateError(ClientError):
    """Raised when a requested field did not persist after a Things write.

    Things 3 accepts several writes that it then ignores, so process exit status
    alone cannot prove an update landed. Every ``update_*`` method reads the row
    back and raises this error naming each requested field that did not persist.
    """
    pass


# `move ... to list` only accepts the Things AppleScript `list` objects. Things
# has no "Tomorrow" or "Evening" list: `move to list "Tomorrow"` fails with
# error 301 ("Cannot move to-do") and `move to list "Evening"` fails with -1728
# ("Can't get list"). Everything below is verified working through AppleScript.
WHEN_LIST_MOVES = {
    "inbox": "Inbox",
    "today": "Today",
    "anytime": "Anytime",
    "someday": "Someday",
}

# `when` values Things only accepts through its URL scheme (see
# THINGS_URL_SCHEME_CLEAR_NOTE).
WHEN_URL_VALUES = ("tomorrow", "evening")

ALL_WHEN_KEYWORDS = tuple(WHEN_LIST_MOVES) + WHEN_URL_VALUES

# Things 3 has no AppleScript path for clearing a date-typed property or an
# object-typed property:
#   set due date of theToDo to missing value        -> -1700
#   set activation date of theToDo to missing value -> -1700 (and the property
#                                                     is read-only in the sdef)
#   set area of theToDo to missing value            -> -1700
# The Things URL scheme documents that "including a parameter with an equals
# sign but without a value will clear that value", and that is the only
# supported clear path. Its `update`/`update-project` commands need the URL
# scheme authentication token, which Things stores locally in
# `TMSettings.uriSchemeAuthenticationToken` in the same database this client
# already reads.
THINGS_URL_SCHEME_CLEAR_NOTE = (
    "Things 3 cannot clear this value through AppleScript, so the CLI uses the "
    "Things URL scheme instead."
)

# Things refuses to change the `when` field of a repeating to-do. AppleScript
# returns 301 (move) or 302 (schedule), and the URL scheme silently ignores the
# parameter: "This field cannot be updated on repeating to-dos."
REPEATING_WHEN_UNSUPPORTED = (
    "Things 3 does not allow the `when` field of a repeating to-do to be "
    "changed from outside the app. AppleScript returns \"Cannot move to-do "
    "(301)\" or \"Cannot schedule to-do (302)\", and the Things URL scheme "
    "ignores the parameter. Change the repeat schedule in the Things app, or "
    "reschedule a generated instance of the repeating to-do instead."
)


# Things 3 silently truncated a reproduced ASCII todo-notes AppleScript write
# after 39,999 characters. Use the conservative NSString-compatible UTF-16
# measure before dispatch so non-BMP text cannot exceed the observed budget and
# a successful process exit can never conceal a lossy write.
THINGS_NOTES_MAX_UTF16_UNITS = 39_999


def _utf16_code_units(value: str) -> int:
    """Return NSString-compatible UTF-16 code-unit length."""
    return len(value.encode("utf-16-le")) // 2


def _validate_notes_length(notes: Optional[str]) -> None:
    """Reject notes that Things 3 would silently truncate."""
    if notes is None:
        return
    units = _utf16_code_units(notes)
    if units > THINGS_NOTES_MAX_UTF16_UNITS:
        raise ClientError(
            "Things 3 supports at most "
            f"{THINGS_NOTES_MAX_UTF16_UNITS:,} UTF-16 code units in todo notes; "
            f"received {units:,} code units ({len(notes):,} Python characters). "
            "No Things record was created or updated. Shorten or split the notes "
            "and retry."
        )


def _glob_database_worker(pattern: str, protected_root: Optional[str], queue):
    """Run protected Things database glob in a killable child process."""
    try:
        if protected_root:
            try:
                with os.scandir(protected_root):
                    pass
            except FileNotFoundError:
                pass
            except PermissionError as exc:
                queue.put(("permission", str(exc)))
                return
        queue.put(("ok", glob(pattern)))
    except PermissionError as exc:
        queue.put(("permission", str(exc)))
    except Exception as exc:  # pragma: no cover - defensive for child process failures
        queue.put(("error", repr(exc)))


class ThingsClient:
    """Client for interacting with Things 3 SQLite database."""

    # Database path pattern for Things 3
    DB_CONTAINER = "Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac"
    DB_PATTERN = f"{DB_CONTAINER}/ThingsData-*/Things Database.thingsdatabase/main.sqlite"

    def __init__(self, require_database: bool = True):
        """Initialize the client, optionally without protected SQLite access.

        AppleScript-only create operations must not be blocked before dispatch by
        macOS TCC on the separate SQLite readback channel.
        """
        self.db_path: Optional[Path] = None
        if require_database:
            self.db_path = self._discover_database()
            self._validate_database()

    def _things_tcc_message(self) -> str:
        executable = os.path.realpath(sys.executable)
        return (
            "macOS privacy/TCC is blocking filesystem access to Things data. "
            f"Grant Full Disk Access to the responsible Python binary ({executable}), "
            "then retry."
        )

    def _glob_database_with_timeout(
        self,
        pattern: str,
        timeout: float = 5.0,
        protected_root: Optional[str] = None,
    ) -> List[str]:
        """Glob the protected Things container without allowing TCC to hang forever."""
        ctx = mp.get_context("fork")
        queue = ctx.Queue()
        proc = ctx.Process(target=_glob_database_worker, args=(pattern, protected_root, queue))
        proc.start()
        proc.join(timeout)

        if proc.is_alive():
            proc.terminate()
            proc.join(1)
            raise ClientError(
                "Timed out while accessing the Things database container. "
                + self._things_tcc_message()
            )

        if queue.empty():
            raise ClientError(
                "Things database discovery failed before returning a result. "
                "Check macOS privacy permissions for the Python binary running this CLI."
            )

        status, payload = queue.get()
        if status == "permission":
            raise ClientError(
                "Permission denied while accessing the Things database container. "
                + self._things_tcc_message()
                + f" Underlying error: {payload}"
            )
        if status == "error":
            raise ClientError(f"Things database discovery failed: {payload}")
        return payload

    def _discover_database(self) -> Path:
        """Find the Things database path.

        Returns:
            Path to the database file

        Raises:
            ClientError: If database not found
        """
        container = Path.home() / self.DB_CONTAINER
        pattern = str(Path.home() / self.DB_PATTERN)
        matches = self._glob_database_with_timeout(pattern, protected_root=str(container))
        if not matches:
            raise ClientError(
                "Things database not found. "
                "Is Things 3 installed? "
                f"Expected at: {pattern}"
            )
        return Path(matches[0])

    def _validate_database(self):
        """Verify database has the expected schema.

        Raises:
            ClientError: If required tables are missing
        """
        with self._connect(readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            required = {'TMTask', 'TMArea', 'TMTag', 'TMChecklistItem', 'TMTaskTag'}
            missing = required - tables
            if missing:
                raise ClientError(f"Database schema invalid: missing tables {missing}")

    def _check_app_running(self) -> bool:
        """Check if Things.app is currently running.

        Returns:
            True if Things is running, False otherwise
        """
        result = subprocess.run(['pgrep', '-x', 'Things3'], capture_output=True)
        return result.returncode == 0

    def _connect(self, readonly: bool = True) -> sqlite3.Connection:
        """Get database connection.

        Args:
            readonly: If True, open in read-only mode

        Returns:
            SQLite connection

        Raises:
            ClientError: If write requested while app is running
        """
        if not readonly and self._check_app_running():
            raise ClientError(
                "Cannot write while Things app is running. "
                "Please close Things and retry."
            )

        if self.db_path is None:
            self.db_path = self._discover_database()
            self._validate_database()

        mode = 'ro' if readonly else 'rw'
        uri = f"file:{self.db_path}?mode={mode}"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _generate_uuid(self) -> str:
        """Generate a Things-compatible 26-character UUID.

        Things uses alphanumeric UUIDs of 26 characters.
        """
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(26))

    def _timestamp_to_iso(self, ts: Optional[float]) -> Optional[str]:
        """Convert Unix timestamp to ISO date string."""
        if ts is None:
            return None
        try:
            return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
        except (ValueError, OSError):
            return None

    def _date_int_to_iso(self, date_int: Optional[int]) -> Optional[str]:
        """Convert Things packed date integer to ISO date string.

        Things 3 stores startDate and deadline as a packed integer with the
        layout (year << 16) | (month << 12) | (day << 7). The low 7 bits
        encode optional time-of-day info that we ignore for date-only fields.
        """
        if date_int is None:
            return None
        try:
            year = date_int >> 16
            month = (date_int >> 12) & 0xF
            day = (date_int >> 7) & 0x1F
            if not (1 <= month <= 12 and 1 <= day <= 31 and year >= 1900):
                return None
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except (ValueError, OverflowError):
            return None

    def _iso_to_date_int(self, iso_date: Optional[str]) -> Optional[int]:
        """Convert ISO date string to Things packed date integer.

        Inverse of `_date_int_to_iso`. Used when writing date columns directly;
        the standard write paths in this client use AppleScript instead, but
        this helper is provided for completeness and parity.
        """
        if iso_date is None:
            return None
        try:
            date = datetime.strptime(iso_date, '%Y-%m-%d')
            return (date.year << 16) | (date.month << 12) | (date.day << 7)
        except ValueError:
            return None

    def _today_date_int(self) -> int:
        """Return today's date in Things packed integer format."""
        return self._iso_to_date_int(datetime.now().strftime('%Y-%m-%d'))

    # ==================== Auth Methods ====================

    def auth_status(self) -> AuthStatus:
        """Check authentication/database status.

        For Things, we check database accessibility rather than traditional auth.
        """
        try:
            self._validate_database()
            app_running = self._check_app_running()
            return AuthStatus(
                authenticated=True,
                database_path=str(self.db_path),
                app_running=app_running,
                message="Database accessible" + (" (app running, writes blocked)" if app_running else "")
            )
        except ClientError as e:
            return AuthStatus(
                authenticated=False,
                database_path=None,
                app_running=False,
                message=str(e)
            )

    # ==================== Read Methods ====================

    def _get_tag_titles(self, conn: sqlite3.Connection, task_uuid: str) -> List[str]:
        """Get tag titles for a task."""
        cursor = conn.execute(
            """
            SELECT t.title FROM TMTag t
            JOIN TMTaskTag tt ON t.uuid = tt.tags
            WHERE tt.tasks = ?
            ORDER BY t.title
            """,
            (task_uuid,)
        )
        return [row['title'] for row in cursor.fetchall()]

    def _get_checklist_items(self, conn: sqlite3.Connection, task_uuid: str) -> List[ChecklistItem]:
        """Get checklist items for a task."""
        cursor = conn.execute(
            """
            SELECT uuid, title, status, `index`
            FROM TMChecklistItem
            WHERE task = ?
            ORDER BY `index`
            """,
            (task_uuid,)
        )
        return [
            ChecklistItem(
                uuid=row['uuid'],
                title=row['title'] or '',
                status=TaskStatus(row['status']) if row['status'] is not None else TaskStatus.INCOMPLETE,
                index=row['index'] or 0
            )
            for row in cursor.fetchall()
        ]

    def _get_project_title(self, conn: sqlite3.Connection, project_uuid: Optional[str]) -> Optional[str]:
        """Get project title by UUID."""
        if project_uuid is None:
            return None
        cursor = conn.execute(
            "SELECT title FROM TMTask WHERE uuid = ? AND type = 1",
            (project_uuid,)
        )
        row = cursor.fetchone()
        return row['title'] if row else None

    def _get_area_title(self, conn: sqlite3.Connection, area_uuid: Optional[str]) -> Optional[str]:
        """Get area title by UUID."""
        if area_uuid is None:
            return None
        cursor = conn.execute(
            "SELECT title FROM TMArea WHERE uuid = ?",
            (area_uuid,)
        )
        row = cursor.fetchone()
        return row['title'] if row else None

    def _get_effective_area_title(
        self,
        conn: sqlite3.Connection,
        area_uuid: Optional[str],
        project_uuid: Optional[str]
    ) -> Optional[str]:
        """Get area title from todo's area or project's area."""
        # First check todo's direct area
        if area_uuid:
            return self._get_area_title(conn, area_uuid)
        # Otherwise check project's area
        if project_uuid:
            cursor = conn.execute(
                "SELECT area FROM TMTask WHERE uuid = ? AND type = 1",
                (project_uuid,)
            )
            row = cursor.fetchone()
            if row and row['area']:
                return self._get_area_title(conn, row['area'])
        return None

    def _row_to_task(self, row: sqlite3.Row, conn: sqlite3.Connection) -> Task:
        """Convert database row to Task model."""
        uuid = row['uuid']
        area_uuid = row['area']
        project_uuid = row['project']
        return Task(
            uuid=uuid,
            title=row['title'] or '',
            type=TaskType(row['type']) if row['type'] is not None else TaskType.TODO,
            status=TaskStatus(row['status']) if row['status'] is not None else TaskStatus.INCOMPLETE,
            start=StartType(row['start']) if row['start'] is not None else StartType.ANYTIME,
            notes=row['notes'],
            start_date=self._date_int_to_iso(row['startDate']),
            deadline=self._date_int_to_iso(row['deadline']),
            trashed=bool(row['trashed']),
            area_uuid=area_uuid,
            area=self._get_effective_area_title(conn, area_uuid, project_uuid),
            project_uuid=project_uuid,
            project=self._get_project_title(conn, project_uuid),
            heading_uuid=row['heading'],
            checklist_items=self._get_checklist_items(conn, uuid),
            tags=self._get_tag_titles(conn, uuid),
            creation_date=self._timestamp_to_iso(row['creationDate']),
            modification_date=self._timestamp_to_iso(row['userModificationDate']),
        )

    def list_todos(
        self,
        when: Optional[str] = None,
        status: Optional[str] = None,
        tag: Optional[str] = None,
        area: Optional[str] = None,
        project: Optional[str] = None,
        limit: Optional[int] = None,
        include_trashed: bool = False,
    ) -> List[Task]:
        """List todos with optional filters.

        Args:
            when: Filter by 'when' field: inbox, today, anytime, upcoming, someday
            status: Filter by status: incomplete, completed
            tag: Filter by tag title
            area: Filter by area UUID
            project: Filter by project UUID
            limit: Maximum results to return
            include_trashed: Include todos in trashed projects (default: False)

        Returns:
            List of Task models
        """
        with self._connect(readonly=True) as conn:
            # Join with project to filter out todos in trashed projects
            query = """
                SELECT t.* FROM TMTask t
                LEFT JOIN TMTask p ON t.project = p.uuid AND p.type = 1
                WHERE t.type = 0 AND t.trashed = 0
            """
            params = []

            if not include_trashed:
                query += " AND (t.project IS NULL OR p.trashed = 0)"

            if status == 'completed':
                query += " AND t.status = 3"
            elif status == 'incomplete':
                query += " AND t.status = 0"

            if when == 'inbox':
                query += " AND t.start = 0 AND t.project IS NULL"
            elif when == 'anytime':
                query += " AND t.start = 1 AND (t.startDate IS NULL OR t.startDate <= ?)"
                params.append(self._today_date_int())
            elif when == 'someday':
                # Things stores a scheduled (Upcoming) to-do as start=2 plus an
                # activation date. Only a start=2 row with no activation date is
                # actually in the Someday list.
                query += " AND t.start = 2 AND t.startDate IS NULL"
            elif when == 'today':
                query += " AND t.startDate <= ?"
                params.append(self._today_date_int())
            elif when == 'upcoming':
                query += " AND t.startDate > ?"
                params.append(self._today_date_int())

            if area:
                # Match todos directly in area OR todos in projects that are in the area
                query += " AND (t.area = ? OR p.area = ?)"
                params.append(area)
                params.append(area)

            if project:
                query += " AND t.project = ?"
                params.append(project)

            query += " ORDER BY t.todayIndex, t.`index`"

            if limit:
                query += f" LIMIT {int(limit)}"

            cursor = conn.execute(query, params)
            tasks = [self._row_to_task(row, conn) for row in cursor.fetchall()]

            # Post-filter by tag if specified (tag is a title, not UUID)
            if tag:
                tasks = [t for t in tasks if tag in t.tags]

            return tasks

    def list_next_actions(self, limit: Optional[int] = None) -> List[Task]:
        """List actionable todos (next actions).

        Returns todos that:
        - Are incomplete
        - Have no tags
        - Are in a non-trashed project
        - Have no incomplete WF-tagged task ahead of them in the same project

        Args:
            limit: Maximum results to return

        Returns:
            List of actionable Task models
        """
        with self._connect(readonly=True) as conn:
            # Get all incomplete todos in non-trashed projects, ordered by project and index
            query = """
                SELECT t.*, t.`index` as task_index
                FROM TMTask t
                JOIN TMTask p ON t.project = p.uuid AND p.type = 1
                WHERE t.type = 0
                  AND t.trashed = 0
                  AND t.status = 0
                  AND t.project IS NOT NULL
                  AND p.trashed = 0
                ORDER BY t.project, t.`index`
            """
            cursor = conn.execute(query)
            all_todos = []
            for row in cursor.fetchall():
                task = self._row_to_task(row, conn)
                task._index = row['task_index']  # Store index for comparison
                all_todos.append(task)

            # Group todos by project
            project_todos: dict = {}
            for todo in all_todos:
                if todo.project_uuid not in project_todos:
                    project_todos[todo.project_uuid] = []
                project_todos[todo.project_uuid].append(todo)

            # Filter for next actions
            next_actions = []
            for project_uuid, todos in project_todos.items():
                # Sort by index within project
                todos.sort(key=lambda t: getattr(t, '_index', 0))

                for i, todo in enumerate(todos):
                    # Skip if todo has any tags
                    if todo.tags:
                        continue

                    # Check if any WF-tagged incomplete task is ahead
                    has_wf_ahead = False
                    for earlier_todo in todos[:i]:
                        if 'WF' in earlier_todo.tags:
                            has_wf_ahead = True
                            break

                    if not has_wf_ahead:
                        next_actions.append(todo)

            # Clean up temporary _index attribute
            for task in next_actions:
                if hasattr(task, '_index'):
                    delattr(task, '_index')

            if limit:
                next_actions = next_actions[:limit]

            return next_actions

    def get_todo(self, uuid: str) -> Task:
        """Get a single todo by UUID.

        Args:
            uuid: Task UUID

        Returns:
            Task model

        Raises:
            ClientError: If todo not found
        """
        with self._connect(readonly=True) as conn:
            cursor = conn.execute(
                "SELECT * FROM TMTask WHERE uuid = ? AND type = 0",
                (uuid,)
            )
            row = cursor.fetchone()
            if not row:
                raise ClientError(f"Todo not found: {uuid}")
            return self._row_to_task(row, conn)

    def _resolve_todo_completion_uuid(self, uuid: str) -> str:
        """Resolve a recurring backing todo to its active generated instance.

        Things stores repeating todos as a backing/template row plus separate
        generated instance rows. The backing row is not what the Today view
        completes. When callers pass a backing UUID, complete the open generated
        instance due today or earlier.
        """
        with self._connect(readonly=True) as conn:
            cursor = conn.execute(
                "SELECT * FROM TMTask WHERE uuid = ? AND type = 0",
                (uuid,)
            )
            row = cursor.fetchone()
            if not row:
                raise ClientError(f"Todo not found: {uuid}")

            repeating_template = row['rt1_repeatingTemplate']
            recurrence_rule = row['rt1_recurrenceRule']
            if repeating_template or recurrence_rule is None:
                return uuid

            today_int = self._today_date_int()
            cursor = conn.execute(
                """
                SELECT uuid FROM TMTask
                WHERE type = 0
                  AND trashed = 0
                  AND status = 0
                  AND rt1_repeatingTemplate = ?
                  AND startDate IS NOT NULL
                  AND startDate <= ?
                ORDER BY startDate DESC, todayIndex, `index`
                LIMIT 1
                """,
                (uuid, today_int),
            )
            instance = cursor.fetchone()
            if not instance:
                return uuid
            return instance['uuid']

    def list_projects(
        self,
        area: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Project]:
        """List projects with optional filters."""
        with self._connect(readonly=True) as conn:
            query = "SELECT * FROM TMTask WHERE type = 1 AND trashed = 0"
            params = []

            if status == 'completed':
                query += " AND status = 3"
            elif status == 'incomplete':
                query += " AND status = 0"

            if area:
                query += " AND area = ?"
                params.append(area)

            query += " ORDER BY `index`"

            if limit:
                query += f" LIMIT {int(limit)}"

            cursor = conn.execute(query, params)
            return [
                Project(
                    uuid=row['uuid'],
                    title=row['title'] or '',
                    status=TaskStatus(row['status']) if row['status'] is not None else TaskStatus.INCOMPLETE,
                    start=StartType(row['start']) if row['start'] is not None else StartType.ANYTIME,
                    notes=row['notes'],
                    start_date=self._date_int_to_iso(row['startDate']),
                    deadline=self._date_int_to_iso(row['deadline']),
                    trashed=bool(row['trashed']),
                    area_uuid=row['area'],
                    area=self._get_area_title(conn, row['area']),
                    tags=self._get_tag_titles(conn, row['uuid']),
                    creation_date=self._timestamp_to_iso(row['creationDate']),
                    modification_date=self._timestamp_to_iso(row['userModificationDate']),
                )
                for row in cursor.fetchall()
            ]

    def get_project(self, uuid: str) -> Project:
        """Get a single project by UUID."""
        with self._connect(readonly=True) as conn:
            cursor = conn.execute(
                "SELECT * FROM TMTask WHERE uuid = ? AND type = 1",
                (uuid,)
            )
            row = cursor.fetchone()
            if not row:
                raise ClientError(f"Project not found: {uuid}")
            return Project(
                uuid=row['uuid'],
                title=row['title'] or '',
                status=TaskStatus(row['status']) if row['status'] is not None else TaskStatus.INCOMPLETE,
                start=StartType(row['start']) if row['start'] is not None else StartType.ANYTIME,
                notes=row['notes'],
                start_date=self._date_int_to_iso(row['startDate']),
                deadline=self._date_int_to_iso(row['deadline']),
                trashed=bool(row['trashed']),
                area_uuid=row['area'],
                area=self._get_area_title(conn, row['area']),
                tags=self._get_tag_titles(conn, row['uuid']),
                creation_date=self._timestamp_to_iso(row['creationDate']),
                modification_date=self._timestamp_to_iso(row['userModificationDate']),
            )

    def list_areas(self, limit: Optional[int] = None) -> List[Area]:
        """List all areas."""
        with self._connect(readonly=True) as conn:
            query = "SELECT * FROM TMArea ORDER BY `index`"
            if limit:
                query += f" LIMIT {int(limit)}"
            cursor = conn.execute(query)
            return [
                Area(
                    uuid=row['uuid'],
                    title=row['title'] or '',
                    visible=bool(row['visible']) if row['visible'] is not None else True,
                    index=row['index'] or 0
                )
                for row in cursor.fetchall()
            ]

    def get_area(self, uuid: str) -> Area:
        """Get a single area by UUID."""
        with self._connect(readonly=True) as conn:
            cursor = conn.execute("SELECT * FROM TMArea WHERE uuid = ?", (uuid,))
            row = cursor.fetchone()
            if not row:
                raise ClientError(f"Area not found: {uuid}")
            return Area(
                uuid=row['uuid'],
                title=row['title'] or '',
                visible=bool(row['visible']) if row['visible'] is not None else True,
                index=row['index'] or 0
            )

    def list_tags(self, limit: Optional[int] = None) -> List[Tag]:
        """List all tags."""
        with self._connect(readonly=True) as conn:
            query = "SELECT * FROM TMTag ORDER BY `index`"
            if limit:
                query += f" LIMIT {int(limit)}"
            cursor = conn.execute(query)
            return [
                Tag(
                    uuid=row['uuid'],
                    title=row['title'] or '',
                    shortcut=row['shortcut'],
                    parent_uuid=row['parent'],
                    index=row['index'] or 0
                )
                for row in cursor.fetchall()
            ]

    def get_tag(self, uuid: str) -> Tag:
        """Get a single tag by UUID."""
        with self._connect(readonly=True) as conn:
            cursor = conn.execute("SELECT * FROM TMTag WHERE uuid = ?", (uuid,))
            row = cursor.fetchone()
            if not row:
                raise ClientError(f"Tag not found: {uuid}")
            return Tag(
                uuid=row['uuid'],
                title=row['title'] or '',
                shortcut=row['shortcut'],
                parent_uuid=row['parent'],
                index=row['index'] or 0
            )

    # ==================== Write Methods (AppleScript) ====================
    # All write operations use AppleScript to ensure proper sync metadata handling

    def _run_applescript(self, script: str, timeout: int = 30) -> str:
        """Run an AppleScript and return the output.

        Args:
            script: AppleScript code to execute
            timeout: Wall-clock timeout in seconds before subprocess is killed.
                Things3 AppleScript writes occasionally hang (e.g. immediately
                after first launch of a freshly installed App Store build, or
                during Things Cloud sync). A bounded timeout converts that into
                a clear, actionable error instead of an indefinite hang.

        Returns:
            stdout from the script

        Raises:
            ClientError: If the script fails or exceeds the timeout
        """
        try:
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise AppleScriptTimeoutError(
                f"AppleScript timed out after {timeout}s. Things3 may be "
                "unresponsive, syncing, or awaiting first-launch interaction "
                "(accept terms / Things Cloud setup). Bring Things3 to the "
                "foreground, dismiss any modal dialogs, then retry. If the "
                "problem persists, also verify Automation permission for "
                "Things3 in System Settings > Privacy & Security > Automation."
            )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            raise ClientError(f"AppleScript error: {error_msg}")

        return result.stdout.strip()

    def _task_update_timeout_message(
        self,
        uuid: str,
        before: Task,
        after: Optional[Task],
        original_error: AppleScriptTimeoutError,
    ) -> str:
        """Build a timeout error that reports the durable read-back state.

        AppleScript writes can partially commit before osascript is killed by the
        subprocess timeout. Returning the generic timeout hides that state and
        encourages blind retries. Include before/after SQLite state so callers
        know whether a field changed unexpectedly, especially status.
        """
        message = str(original_error)
        if after is None:
            return (
                f"{message} Read-back after the timeout failed for todo {uuid}; "
                "do not blindly retry until Things3 is responsive and the task "
                "state is checked."
            )

        changes = []
        for field in ("title", "notes", "area_uuid", "project_uuid", "status", "start", "deadline", "start_date", "tags"):
            before_value = getattr(before, field)
            after_value = getattr(after, field)
            if before_value != after_value:
                changes.append(f"{field}: {before_value!r} -> {after_value!r}")

        if not changes:
            return (
                f"{message} Read-back after the timeout shows no durable changes "
                f"for todo {uuid}."
            )

        recovery_hint = ""
        if before.status != after.status:
            recovery_hint = (
                " Unexpected status change detected; do not retry the same update "
                "until Things3 is responsive. If recovery is needed, run the "
                "smallest status-only command after confirming current read-back."
            )

        return (
            f"{message} Read-back after the timeout shows partial durable changes "
            f"for todo {uuid}: " + "; ".join(changes) + "." + recovery_hint
        )

    def _recover_project_create_timeout(
        self,
        title: str,
        notes: Optional[str],
        area: Optional[str],
        when: Optional[str],
        original_error: AppleScriptTimeoutError,
    ) -> Project:
        """Read back a project create timeout and return only an unambiguous match.

        A Things AppleEvent can commit the new project before osascript is killed
        by the subprocess timeout, leaving the caller with no returned UUID. Blind
        retries can then create duplicates. Match the intended inputs against
        SQLite and either return the one durable project or fail with a message
        that makes the retry safety explicit.
        """
        try:
            projects = self.list_projects(
                area=area if area else None,
                status="incomplete",
                limit=None,
            )
        except ClientError as readback_error:
            raise ClientError(
                f"{original_error} Read-back after the project-create timeout "
                "failed; do not blindly retry because the project may already "
                f"exist. Read-back error: {readback_error}"
            ) from original_error

        matches = []
        for project in projects:
            if project.title != title:
                continue
            if (project.notes or None) != (notes or None):
                continue
            if area and project.area_uuid != area:
                continue
            if not area and project.area_uuid is not None:
                continue
            matches.append(project)

        if len(matches) == 1:
            project = matches[0]
            if when == "someday" and project.start != StartType.SOMEDAY:
                raise ClientError(
                    f"{original_error} Read-back found one durably-created "
                    f"project ({project.uuid}) matching the requested title, "
                    "notes, and area, but it was not moved to Someday. Do not "
                    "retry create; update or move the existing project after "
                    "Things3 is responsive."
                ) from original_error
            return project

        if not matches:
            raise ClientError(
                f"{original_error} Read-back after the project-create timeout "
                "found no durable project matching the requested title, notes, "
                "and area. Retry only after Things3 is responsive."
            ) from original_error

        uuids = ", ".join(project.uuid for project in matches)
        raise ClientError(
            f"{original_error} Read-back after the project-create timeout found "
            f"multiple matching projects ({uuids}); do not blindly retry create."
        ) from original_error

    def _iso_to_applescript_date(self, iso_date: str) -> str:
        """Convert an ISO date (YYYY-MM-DD) to AppleScript-compatible format.

        AppleScript cannot parse ISO dates like "2026-03-01" correctly.
        It needs "March 1, 2026" format instead.

        Args:
            iso_date: Date string in YYYY-MM-DD format

        Returns:
            Date string in "Month Day, Year" format

        Raises:
            ClientError: If date string is not valid YYYY-MM-DD format
        """
        try:
            dt = datetime.strptime(iso_date, "%Y-%m-%d")
        except ValueError:
            raise ClientError(f"Invalid date format '{iso_date}'. Expected YYYY-MM-DD.")
        return dt.strftime("%B %-d, %Y")

    def _escape_applescript_string(self, s: str) -> str:
        """Escape a string for use in AppleScript."""
        if s is None:
            return ""
        return s.replace('\\', '\\\\').replace('"', '\\"')

    # ==================== Things URL Scheme ====================

    def _url_scheme_token(self) -> str:
        """Read the Things URL scheme authentication token from the database.

        Things stores the token that its own URL scheme requires in
        ``TMSettings.uriSchemeAuthenticationToken``. Reading it here keeps the
        token in exactly one place (the live Things database) instead of a copy
        that can go stale.

        Raises:
            ClientError: If the token row is missing or empty.
        """
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                "SELECT uriSchemeAuthenticationToken FROM TMSettings LIMIT 1"
            ).fetchone()

        token = row['uriSchemeAuthenticationToken'] if row else None
        if not token:
            raise ClientError(
                "Things 3 has no URL scheme authentication token. Enable "
                "Things URLs in Things > Settings > General, then retry. "
                + THINGS_URL_SCHEME_CLEAR_NOTE
            )
        return token

    def _run_url_scheme(self, command: str, params: Dict[str, str]) -> None:
        """Send one Things URL scheme command.

        The URL scheme is fire-and-forget: Things returns no result and no error
        for an ignored parameter, so every caller must verify the write through
        ``_verify_persisted_updates``.

        Args:
            command: URL scheme command, for example ``update``.
            params: Query parameters. An empty string value clears that field.

        Raises:
            ClientError: If the `open` command fails.
        """
        query = urlencode({"auth-token": self._url_scheme_token(), **params})
        url = f"things:///{command}?{query}"
        # `-g` keeps Things in the background so a CLI write cannot steal focus.
        result = subprocess.run(
            ['open', '-g', url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise ClientError(
                f"Things URL scheme command '{command}' failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        # Things applies URL scheme commands asynchronously. Callers read the
        # row back afterwards, so give the app a moment to commit first.
        time.sleep(1.0)

    def _is_repeating(self, uuid: str) -> bool:
        """Return True when the row is a repeating template rather than an instance.

        A repeating template owns the recurrence rule and has no parent
        template. Generated instances point back at the template through
        ``rt1_repeatingTemplate``.
        """
        with self._connect(readonly=True) as conn:
            row = conn.execute(
                "SELECT rt1_repeatingTemplate, rt1_recurrenceRule FROM TMTask WHERE uuid = ?",
                (uuid,),
            ).fetchone()
        if not row:
            return False
        return row['rt1_repeatingTemplate'] is None and row['rt1_recurrenceRule'] is not None

    # ==================== Write Verification ====================

    def _normalize_iso_date(self, iso_date: str) -> str:
        """Validate and normalize an ISO date to YYYY-MM-DD."""
        try:
            return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise ClientError(f"Invalid date format '{iso_date}'. Expected YYYY-MM-DD.")

    def _expected_when_state(self, when: str) -> Dict[str, Any]:
        """Return the read-back state a `when` value must produce.

        Verified against Things 3 (database version 26):

        =========================  =====  ==========
        requested when             start  start_date
        =========================  =====  ==========
        ``""`` (clear)             1      ``None``
        ``inbox``                  0      ``None``
        ``anytime``                1      ``None``
        ``someday``                2      ``None``
        ``today``                  1      today
        ``evening``                1      today
        ``tomorrow``               owned  tomorrow
        ISO date                   owned  that date
        =========================  =====  ==========

        Things owns the ``start`` bucket for a dated to-do: it stores a future
        activation date as ``start=2`` with that date (the Upcoming list) and
        promotes the row to ``start=1`` when the date arrives. ``start`` is
        therefore only asserted for the dateless placements and for the two
        keywords that pin the date to today.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        if when == "":
            return {"start": StartType.ANYTIME, "start_date": None}
        if when == "inbox":
            return {"start": StartType.NOT_SET, "start_date": None}
        if when == "anytime":
            return {"start": StartType.ANYTIME, "start_date": None}
        if when == "someday":
            return {"start": StartType.SOMEDAY, "start_date": None}
        if when in ("today", "evening"):
            return {"start": StartType.ANYTIME, "start_date": today}
        if when == "tomorrow":
            return {"start_date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")}
        return {"start_date": self._normalize_iso_date(when)}

    @staticmethod
    def _persisted_value_matches(field: str, expected: Any, actual: Any) -> bool:
        """Compare a requested value against the value Things persisted."""
        if field == "tags":
            return sorted(actual or []) == sorted(expected or [])
        if field == "notes":
            return (actual or "") == (expected or "")
        return actual == expected

    def _verify_persisted_updates(
        self,
        uuid: str,
        entity_name: str,
        expectations: Dict[str, Any],
        after,
    ) -> None:
        """Fail when any requested field did not persist.

        Things accepts and then ignores several writes, so a zero exit status
        from osascript or `open` is not evidence. This is the single gate that
        decides whether an update succeeded.

        Args:
            uuid: Entity UUID.
            entity_name: ``todo`` or ``project``, used in the error message.
            expectations: Read-back attribute name -> required value.
            after: Model read back after the write.

        Raises:
            UnpersistedUpdateError: If any expectation is unmet.
        """
        unpersisted: List[Tuple[str, Any, Any]] = []
        for field, expected in expectations.items():
            actual = getattr(after, field)
            if not self._persisted_value_matches(field, expected, actual):
                unpersisted.append((field, expected, actual))

        if not unpersisted:
            return

        details = "; ".join(
            f"{field}: requested {expected!r}, actual {actual!r}"
            for field, expected, actual in unpersisted
        )
        actual_state = (
            f"start={int(after.start)}, start_date={after.start_date!r}, "
            f"deadline={after.deadline!r}, tags={list(after.tags)!r}"
        )
        message = (
            f"Things 3 did not persist every requested change to {entity_name} "
            f"{uuid}. Unpersisted fields -> {details}. Current state: "
            f"{actual_state}."
        )
        if self._is_repeating(uuid) and any(
            field in ("start", "start_date", "deadline") for field, _, _ in unpersisted
        ):
            message += (
                f" This {entity_name} is a repeating item. "
                + REPEATING_WHEN_UNSUPPORTED
            )
        raise UnpersistedUpdateError(message)

    def _wait_for_status(
        self,
        fetch_item,
        uuid: str,
        expected_status: TaskStatus,
        entity_name: str,
        timeout: float = 5.0,
        poll_interval: float = 0.1,
    ):
        """Wait until SQLite reflects an AppleScript status change.

        Things3 returns from some AppleScript status writes before the backing
        SQLite row is updated. Poll the existing read path until the write is
        durably visible, then return the same model the CLI would normally emit.
        """
        deadline = time.monotonic() + timeout
        last_item = None

        while time.monotonic() < deadline:
            last_item = fetch_item(uuid)
            if last_item.status == expected_status:
                return last_item
            time.sleep(poll_interval)

        if last_item is None:
            raise ClientError(
                f"Timed out waiting for {entity_name} {uuid} to become "
                f"status {int(expected_status)}."
            )

        raise ClientError(
            f"Timed out waiting for {entity_name} {uuid} to become status "
            f"{int(expected_status)}. Last SQLite status was {int(last_item.status)}."
        )

    def create_todo(
        self,
        title: str,
        notes: Optional[str] = None,
        when: Optional[str] = None,
        deadline: Optional[str] = None,
        tags: Optional[List[str]] = None,
        project: Optional[str] = None,
        area: Optional[str] = None,
    ) -> Task:
        """Create a new todo using AppleScript.

        Args:
            title: Todo title
            notes: Optional notes
            when: When to schedule: inbox, today, tomorrow, evening, anytime, someday, or a date
            deadline: Optional deadline in YYYY-MM-DD format
            tags: Optional list of tag titles (not UUIDs)
            project: Optional project UUID or title
            area: Optional area UUID (places todo directly in an area, without a project)

        Returns:
            Created Task model

        Raises:
            ClientError: If AppleScript fails
        """
        _validate_notes_length(notes)
        escaped_title = self._escape_applescript_string(title)

        # Build properties
        props = [f'name:"{escaped_title}"']

        if notes:
            escaped_notes = self._escape_applescript_string(notes)
            props.append(f'notes:"{escaped_notes}"')

        if deadline:
            as_date = self._iso_to_applescript_date(deadline)
            props.append(f'due date:date "{as_date}"')

        if tags:
            tag_str = ", ".join(tags)
            escaped_tags = self._escape_applescript_string(tag_str)
            props.append(f'tag names:"{escaped_tags}"')

        props_str = ", ".join(props)

        # Determine where to create the todo
        if project:
            # Try to find by UUID first, then by name
            location = f'at beginning of project id "{project}"'
        elif when == 'inbox':
            location = 'at beginning of list "Inbox"'
        elif when == 'today':
            location = 'at beginning of list "Today"'
        elif when == 'someday':
            location = 'at beginning of list "Someday"'
        else:
            location = 'at beginning of list "Anytime"'

        script = f'''
        tell application "Things3"
            set newToDo to make new to do with properties {{{props_str}}} {location}
            return id of newToDo
        end tell
        '''

        todo_id = self._run_applescript(script)

        # If the todo was created directly inside a project, Things ignores list
        # placement in the `make new to do ... at beginning of project ...`
        # AppleScript statement and leaves the task in Anytime. Honor explicit
        # --when by applying the same post-create move/schedule operation that
        # `update_todo(..., when=...)` uses; read-back then reflects the
        # requested start value while preserving project membership.
        # `tomorrow` and `evening` are not Things lists, so the create statement
        # above cannot express them; apply them through the same verified
        # update path.
        if when is not None and (
            when in WHEN_URL_VALUES or (project and when in ALL_WHEN_KEYWORDS)
        ):
            self.update_todo(todo_id, when=when)

        # If 'when' is an ISO date (not a keyword), schedule for that date
        if when and when not in ALL_WHEN_KEYWORDS:
            as_date = self._iso_to_applescript_date(when)
            schedule_script = f'''
            tell application "Things3"
                schedule (to do id "{todo_id}") for date "{as_date}"
            end tell
            '''
            self._run_applescript(schedule_script)

        # Assign to area if specified (and not already in a project)
        if area and not project:
            escaped_area = self._escape_applescript_string(area)
            area_script = f'''
            tell application "Things3"
                set theToDo to (to do id "{todo_id}")
                set theArea to area id "{escaped_area}"
                set area of theToDo to theArea
            end tell
            '''
            self._run_applescript(area_script)

        try:
            return self.get_todo(todo_id)
        except ClientError as exc:
            if "macOS privacy/TCC is blocking filesystem access" not in str(exc):
                raise

            start = StartType.ANYTIME
            if when == "inbox":
                start = StartType.NOT_SET
            elif when == "someday":
                start = StartType.SOMEDAY

            return Task(
                uuid=todo_id,
                title=title,
                notes=notes,
                start=start,
                start_date=(
                    when
                    if when and when not in ALL_WHEN_KEYWORDS
                    else None
                ),
                deadline=deadline,
                area_uuid=area,
                project_uuid=project,
                tags=tags or [],
            )

    def complete_todo(self, uuid: str) -> Task:
        """Mark a todo as completed using AppleScript.

        Args:
            uuid: Task UUID

        Returns:
            Updated Task model

        Raises:
            ClientError: If todo not found or AppleScript fails
        """
        completion_uuid = self._resolve_todo_completion_uuid(uuid)
        script = f'''
        tell application "Things3"
            set theToDo to (to do id "{completion_uuid}")
            set status of theToDo to completed
            return id of theToDo
        end tell
        '''

        try:
            self._run_applescript(script)
        except AppleScriptTimeoutError as exc:
            try:
                todo = self.get_todo(completion_uuid)
            except ClientError:
                raise exc
            if todo.status == TaskStatus.COMPLETED:
                return todo
            raise ClientError(
                f"{exc} Read-back after the timeout shows todo {completion_uuid} "
                f"is still status {int(todo.status)}, not {int(TaskStatus.COMPLETED)}."
            ) from exc
        return self._wait_for_status(
            self.get_todo,
            completion_uuid,
            TaskStatus.COMPLETED,
            "todo",
        )

    def uncomplete_todo(self, uuid: str) -> Task:
        """Mark a todo as incomplete using AppleScript.

        Args:
            uuid: Task UUID

        Returns:
            Updated Task model

        Raises:
            ClientError: If todo not found or AppleScript fails
        """
        script = f'''
        tell application "Things3"
            set theToDo to (to do id "{uuid}")
            set status of theToDo to open
            return id of theToDo
        end tell
        '''

        try:
            self._run_applescript(script)
        except AppleScriptTimeoutError as exc:
            try:
                todo = self.get_todo(uuid)
            except ClientError:
                raise exc
            if todo.status == TaskStatus.INCOMPLETE:
                return todo
            raise ClientError(
                f"{exc} Read-back after the timeout shows todo {uuid} "
                f"is still status {int(todo.status)}, not {int(TaskStatus.INCOMPLETE)}."
            ) from exc
        return self._wait_for_status(
            self.get_todo,
            uuid,
            TaskStatus.INCOMPLETE,
            "todo",
        )

    def delete_todo(self, uuid: str) -> dict:
        """Delete a todo (move to trash) using AppleScript.

        Args:
            uuid: Task UUID

        Returns:
            Dict with uuid and deleted status

        Raises:
            ClientError: If todo not found or AppleScript fails
        """
        # Read the current state first. get_todo reads from SQLite, which works
        # for completed/logbook items, so it is the authoritative existence and
        # status check. A missing todo is an error, not a silently-ignored
        # delete of a phantom UUID.
        todo = self.get_todo(uuid)
        title = todo.title

        # Things3 AppleScript cannot delete a completed todo via `to do id`:
        # once a todo is completed it leaves its active list (it lives in the
        # Logbook, or stays under its project but out of the project's `to dos`
        # collection), so `delete (to do id "<uuid>")` raises -1728
        # ("Can't get to do id ..."). The `... of list "Logbook"` selector only
        # resolves completed todos that are NOT in a project, so it is not a
        # universal fix. The one path that resolves and trashes every completed
        # todo (project-scoped or not) is to reopen it and delete it inside a
        # single AppleScript transaction: `to do id` reads fine for a completed
        # todo, `set status to open` returns it to an active list, and `delete`
        # on that same already-resolved reference then succeeds. For an
        # incomplete todo the existing direct-delete path already works, so it
        # is preserved unchanged.
        if todo.status == TaskStatus.INCOMPLETE:
            script = f'''
        tell application "Things3"
            set theToDo to (to do id "{uuid}")
            delete theToDo
        end tell
        '''
        else:
            script = f'''
        tell application "Things3"
            set theToDo to (to do id "{uuid}")
            set status of theToDo to open
            delete theToDo
        end tell
        '''

        try:
            self._run_applescript(script)
        except AppleScriptTimeoutError as exc:
            # osascript can be killed between `set status to open` and `delete`,
            # leaving a previously-completed todo reopened but not trashed.
            # Report the durable read-back state instead of a generic timeout so
            # the caller knows whether the delete completed and whether the
            # status was left changed.
            try:
                after = self.get_todo(uuid)
            except ClientError:
                # The todo is gone from the read path; treat as deleted.
                return {"uuid": uuid, "title": title, "deleted": True}
            if after.trashed:
                return {"uuid": uuid, "title": title, "deleted": True}
            status_note = ""
            if after.status != todo.status:
                status_note = (
                    f" Its status was also changed from {int(todo.status)} to "
                    f"{int(after.status)} before the timeout; the todo is "
                    "recoverable by re-running delete once Things3 is responsive."
                )
            raise ClientError(
                f"{exc} Read-back after the timeout shows todo {uuid} was not "
                f"trashed (trashed={after.trashed}).{status_note}"
            ) from exc

        return {"uuid": uuid, "title": title, "deleted": True}

    def update_todo(
        self,
        uuid: str,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        when: Optional[str] = None,
        deadline: Optional[str] = None,
        tags: Optional[List[str]] = None,
        project: Optional[str] = None,
        area: Optional[str] = None,
    ) -> Task:
        """Update a todo using AppleScript.

        Args:
            uuid: Task UUID
            title: New title (optional)
            notes: New notes (optional)
            when: New when value: inbox, today, tomorrow, evening, anytime,
                someday, an ISO date, or an empty string to clear the date
                (optional)
            deadline: New deadline in YYYY-MM-DD format, or empty string to clear (optional)
            tags: New list of tag titles (replaces existing tags; pass an empty
                list to remove every tag) (optional)
            project: New project UUID to move the todo to (optional). Mutually exclusive with area.
            area: New area UUID to move the todo to (optional, detaches from any
                project), or an empty string to remove the todo from its area
                and project. Mutually exclusive with project.

        Returns:
            Updated Task model

        Raises:
            ClientError: If todo not found or AppleScript fails
            UnpersistedUpdateError: If any requested field did not persist
            ValueError: If both project and area are supplied
        """
        _validate_notes_length(notes)
        if project is not None and area is not None:
            raise ValueError("update_todo: pass only one of `project` or `area`, not both")
        if project == "":
            raise ClientError(
                "A todo cannot be detached from a project with --project \"\". "
                "Use --area \"\" to remove the todo from its project and area, "
                "or --when inbox to move it to the Inbox."
            )

        # Verify todo exists first and keep a pre-write snapshot. If osascript
        # times out, the AppleEvent may still have committed part of the write;
        # compare against the post-timeout SQLite state before reporting.
        before_todo = self.get_todo(uuid)

        # Things refuses `when` changes on a repeating to-do through every
        # supported channel, so reject before writing anything else.
        if when is not None and self._is_repeating(uuid):
            raise ClientError(
                f"Cannot change the when field of todo {uuid} "
                f"('{before_todo.title}'). " + REPEATING_WHEN_UNSUPPORTED
            )

        expectations: Dict[str, Any] = {}

        # Build property updates
        updates = []

        if title is not None:
            escaped_title = self._escape_applescript_string(title)
            updates.append(f'set name of theToDo to "{escaped_title}"')
            expectations["title"] = title

        if notes is not None:
            escaped_notes = self._escape_applescript_string(notes)
            updates.append(f'set notes of theToDo to "{escaped_notes}"')
            expectations["notes"] = notes

        if deadline is not None and deadline != "":
            as_date = self._iso_to_applescript_date(deadline)
            updates.append(f'set due date of theToDo to date "{as_date}"')
            expectations["deadline"] = self._normalize_iso_date(deadline)

        if tags is not None:
            # An empty list clears every tag: Things accepts `set tag names to ""`.
            tag_str = ", ".join(tags)
            escaped_tags = self._escape_applescript_string(tag_str)
            updates.append(f'set tag names of theToDo to "{escaped_tags}"')
            expectations["tags"] = list(tags)

        if project is not None:
            # Reassign the todo to a different project. Things AppleScript
            # exposes this via `set project of theToDo to project id "<uuid>"`.
            updates.append(f'set project of theToDo to project id "{project}"')
            expectations["project_uuid"] = project

        if area is not None and area != "":
            # Reassign the todo to a different area (detaches from any project).
            # Things AppleScript: `set area of theToDo to area id "<uuid>"`.
            updates.append(f'set area of theToDo to area id "{area}"')
            expectations["area_uuid"] = area

        if updates:
            updates_str = "\n            ".join(updates)
            script = f'''
            tell application "Things3"
                set theToDo to (to do id "{uuid}")
                {updates_str}
            end tell
            '''
            self._run_task_write(uuid, before_todo, script)

        # Clears have no AppleScript path; see THINGS_URL_SCHEME_CLEAR_NOTE.
        if deadline == "":
            self._run_url_scheme("update", {"id": uuid, "deadline": ""})
            expectations["deadline"] = None

        if area == "":
            self._run_url_scheme("update", {"id": uuid, "list-id": ""})
            expectations["area_uuid"] = None
            expectations["project_uuid"] = None

        if when is not None:
            self._apply_todo_when(uuid, before_todo, when)
            expectations.update(self._expected_when_state(when))

        after_todo = self.get_todo(uuid)
        self._verify_persisted_updates(uuid, "todo", expectations, after_todo)
        return after_todo

    def _run_task_write(self, uuid: str, before_todo: Task, script: str) -> None:
        """Run one todo AppleScript write, reporting durable state on timeout."""
        try:
            self._run_applescript(script)
        except AppleScriptTimeoutError as exc:
            try:
                after_todo = self.get_todo(uuid)
            except ClientError:
                after_todo = None
            raise ClientError(
                self._task_update_timeout_message(uuid, before_todo, after_todo, exc)
            ) from exc

    def _apply_todo_when(self, uuid: str, before_todo: Task, when: str) -> None:
        """Apply one `when` value through the channel Things supports for it."""
        if when == "":
            # `set activation date to missing value` is rejected (-1700) and the
            # property is read-only in the Things AppleScript dictionary.
            self._run_url_scheme("update", {"id": uuid, "when": ""})
            return

        if when in WHEN_URL_VALUES:
            self._run_url_scheme("update", {"id": uuid, "when": when})
            return

        list_name = WHEN_LIST_MOVES.get(when)
        if list_name is not None:
            move_script = f'''
            tell application "Things3"
                set theToDo to (to do id "{uuid}")
                move theToDo to list "{list_name}"
            end tell
            '''
            self._run_task_write(uuid, before_todo, move_script)
            return

        as_date = self._iso_to_applescript_date(when)
        schedule_script = f'''
        tell application "Things3"
            schedule (to do id "{uuid}") for date "{as_date}"
        end tell
        '''
        self._run_task_write(uuid, before_todo, schedule_script)

    def create_project(
        self,
        title: str,
        notes: Optional[str] = None,
        area: Optional[str] = None,
        when: Optional[str] = None,
    ) -> Project:
        """Create a new project using AppleScript.

        Args:
            title: Project title
            notes: Optional notes
            area: Optional area UUID or title
            when: When to schedule: anytime, someday (default: anytime)

        Returns:
            Created Project model

        Raises:
            ClientError: If AppleScript fails
        """
        escaped_title = self._escape_applescript_string(title)

        # Build properties
        props = [f'name:"{escaped_title}"']

        if notes:
            escaped_notes = self._escape_applescript_string(notes)
            props.append(f'notes:"{escaped_notes}"')

        props_str = ", ".join(props)

        # Build the script.
        # When an area is supplied, resolve it BEFORE `make new project` and
        # pass it inside the property bag. This makes creation atomic: a
        # hang/failure cannot leave an "orphan" project sitting in the inbox
        # with no area, which is what happened when area assignment was a
        # separate post-creation statement.
        if area:
            props_str_with_area = props_str + ", area:theArea"
            script = f'''
            tell application "Things3"
                set theArea to area id "{area}"
                set newProject to make new project with properties {{{props_str_with_area}}}
                return id of newProject
            end tell
            '''
        else:
            script = f'''
            tell application "Things3"
                set newProject to make new project with properties {{{props_str}}}
                return id of newProject
            end tell
            '''

        # Handle 'when' by moving to appropriate list after creation
        try:
            project_id = self._run_applescript(script)
        except AppleScriptTimeoutError as exc:
            return self._recover_project_create_timeout(title, notes, area, when, exc)

        if when == 'someday':
            move_script = f'''
            tell application "Things3"
                move project id "{project_id}" to list "Someday"
            end tell
            '''
            try:
                self._run_applescript(move_script)
            except AppleScriptTimeoutError as exc:
                project = self.get_project(project_id)
                if project.start == StartType.SOMEDAY:
                    return project
                raise ClientError(
                    f"{exc} Project {project_id} was created, but read-back shows "
                    "it was not moved to Someday. Do not retry create; update or "
                    "move the existing project after Things3 is responsive."
                ) from exc

        return self.get_project(project_id)

    def complete_project(self, uuid: str) -> Project:
        """Mark a project as completed using AppleScript.

        Args:
            uuid: Project UUID

        Returns:
            Updated Project model

        Raises:
            ClientError: If project not found or AppleScript fails
        """
        script = f'''
        tell application "Things3"
            set theProject to project id "{uuid}"
            set status of theProject to completed
            return id of theProject
        end tell
        '''

        self._run_applescript(script)
        return self._wait_for_status(
            self.get_project,
            uuid,
            TaskStatus.COMPLETED,
            "project",
        )

    def delete_project(self, uuid: str) -> dict:
        """Delete a project (move to trash) using AppleScript.

        Args:
            uuid: Project UUID

        Returns:
            Dict with uuid and deleted status

        Raises:
            ClientError: If project not found or AppleScript fails
        """
        # Get title before deletion for response
        try:
            project = self.get_project(uuid)
            title = project.title
        except ClientError:
            title = uuid

        script = f'''
        tell application "Things3"
            set theProject to project id "{uuid}"
            delete theProject
        end tell
        '''

        self._run_applescript(script)
        return {"uuid": uuid, "title": title, "deleted": True}

    def update_project(
        self,
        uuid: str,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        area: Optional[str] = None,
        when: Optional[str] = None,
        deadline: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Project:
        """Update a project using AppleScript.

        Args:
            uuid: Project UUID
            title: New title (optional)
            notes: New notes (optional)
            area: New area UUID, or empty string to remove from area (optional)
            when: New when value: anytime, someday (optional)
            deadline: New deadline in YYYY-MM-DD format, or empty string to clear (optional)
            tags: New list of tag titles (replaces existing tags; pass an empty
                list to remove every tag) (optional)

        Returns:
            Updated Project model

        Raises:
            ClientError: If project not found, AppleScript fails, or `when` is
                not one of anytime/someday
            UnpersistedUpdateError: If any requested field did not persist
        """
        # Verify project exists first
        self.get_project(uuid)

        if when is not None and when not in ("anytime", "someday"):
            raise ClientError(
                f"Invalid project when value '{when}'. "
                "Use 'anytime' or 'someday'."
            )

        expectations: Dict[str, Any] = {}

        # Build property updates
        updates = []

        if title is not None:
            escaped_title = self._escape_applescript_string(title)
            updates.append(f'set name of theProject to "{escaped_title}"')
            expectations["title"] = title

        if notes is not None:
            escaped_notes = self._escape_applescript_string(notes)
            updates.append(f'set notes of theProject to "{escaped_notes}"')
            expectations["notes"] = notes

        if deadline is not None and deadline != "":
            as_date = self._iso_to_applescript_date(deadline)
            updates.append(f'set due date of theProject to date "{as_date}"')
            expectations["deadline"] = self._normalize_iso_date(deadline)

        if tags is not None:
            tag_str = ", ".join(tags)
            escaped_tags = self._escape_applescript_string(tag_str)
            updates.append(f'set tag names of theProject to "{escaped_tags}"')
            expectations["tags"] = list(tags)

        if updates:
            updates_str = "\n            ".join(updates)
            script = f'''
            tell application "Things3"
                set theProject to project id "{uuid}"
                {updates_str}
            end tell
            '''
            self._run_applescript(script)

        if deadline == "":
            # `set due date of theProject to missing value` fails with -1700.
            self._run_url_scheme("update-project", {"id": uuid, "deadline": ""})
            expectations["deadline"] = None

        # Handle area assignment
        if area is not None:
            if area == "":
                # `set area of theProject to missing value` fails with -1700.
                self._run_url_scheme("update-project", {"id": uuid, "area-id": ""})
                expectations["area_uuid"] = None
            else:
                area_script = f'''
                tell application "Things3"
                    set theProject to project id "{uuid}"
                    set area of theProject to area id "{area}"
                end tell
                '''
                self._run_applescript(area_script)
                expectations["area_uuid"] = area

        # Handle 'when' by moving to appropriate list
        if when is not None:
            list_name = "Anytime" if when == "anytime" else "Someday"
            move_script = f'''
            tell application "Things3"
                move project id "{uuid}" to list "{list_name}"
            end tell
            '''
            self._run_applescript(move_script)
            expectations.update(self._expected_when_state(when))

        project = self.get_project(uuid)
        self._verify_persisted_updates(uuid, "project", expectations, project)
        return project

    def create_area(self, title: str) -> Area:
        """Create a new area using AppleScript.

        Args:
            title: Area title

        Returns:
            Created Area model

        Raises:
            ClientError: If AppleScript fails
        """
        escaped_title = self._escape_applescript_string(title)

        script = f'''
        tell application "Things3"
            set newArea to make new area with properties {{name:"{escaped_title}"}}
            return id of newArea
        end tell
        '''

        area_id = self._run_applescript(script)
        return self.get_area(area_id)

    def delete_area(self, uuid: str) -> dict:
        """Delete an area using AppleScript.

        Args:
            uuid: Area UUID

        Returns:
            Dict with uuid and deleted status

        Raises:
            ClientError: If area not found or AppleScript fails
        """
        # Get title before deletion for response
        try:
            area = self.get_area(uuid)
            title = area.title
        except ClientError:
            title = uuid

        script = f'''
        tell application "Things3"
            set theArea to area id "{uuid}"
            delete theArea
        end tell
        '''

        self._run_applescript(script)
        return {"uuid": uuid, "title": title, "deleted": True}

    def update_area(
        self,
        uuid: str,
        title: Optional[str] = None,
    ) -> Area:
        """Update an area using AppleScript.

        Args:
            uuid: Area UUID
            title: New title (optional)

        Returns:
            Updated Area model

        Raises:
            ClientError: If area not found or AppleScript fails
        """
        # Verify area exists first
        self.get_area(uuid)

        if title is not None:
            escaped_title = self._escape_applescript_string(title)
            script = f'''
            tell application "Things3"
                set theArea to area id "{uuid}"
                set name of theArea to "{escaped_title}"
            end tell
            '''
            self._run_applescript(script)

        return self.get_area(uuid)

    # ==================== Template Compatibility ====================
    # These methods provide compatibility with the CLI template

    def list_items(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[Task]:
        """List items (alias for list_todos for template compatibility)."""
        return self.list_todos(limit=limit)

    def get_item(self, item_id: str) -> Task:
        """Get item (alias for get_todo for template compatibility)."""
        return self.get_todo(item_id)


# Module-level client instance - singleton pattern
_client: Optional[ThingsClient] = None


def get_client(require_database: bool = True) -> ThingsClient:
    """Get or create the global Things client instance."""
    global _client
    if _client is None:
        _client = ThingsClient(require_database=require_database)
    elif require_database and _client.db_path is None:
        _client.db_path = _client._discover_database()
        _client._validate_database()
    return _client
