"""Things 3 SQLite database client.

Direct SQLite access to the Things 3 database for read and write operations.
- Reads: Safe anytime (database uses WAL mode for concurrent reads)
- Writes: Only when Things.app is not running (to prevent corruption)
"""
import secrets
import sqlite3
import string
import subprocess
import time
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import List, Optional

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


class ThingsClient:
    """Client for interacting with Things 3 SQLite database."""

    # Database path pattern for Things 3
    DB_PATTERN = "Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite"

    def __init__(self):
        """Initialize Things client and discover database."""
        self.db_path = self._discover_database()
        self._validate_database()

    def _discover_database(self) -> Path:
        """Find the Things database path.

        Returns:
            Path to the database file

        Raises:
            ClientError: If database not found
        """
        pattern = str(Path.home() / self.DB_PATTERN)
        matches = glob(pattern)
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
                query += " AND t.start = 2"
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
            raise ClientError(
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

        # If 'when' is an ISO date (not a keyword), schedule for that date
        if when and when not in ('inbox', 'today', 'tomorrow', 'evening', 'anytime', 'someday'):
            as_date = self._iso_to_applescript_date(when)
            schedule_script = f'''
            tell application "Things3"
                schedule (to do id "{todo_id}") for date "{as_date}"
            end tell
            '''
            self._run_applescript(schedule_script)

        # Assign to area if specified (and not already in a project)
        if area and not project:
            area_script = f'''
            tell application "Things3"
                set theToDo to (to do id "{todo_id}")
                set area of theToDo to area id "{area}"
            end tell
            '''
            self._run_applescript(area_script)

        return self.get_todo(todo_id)

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

        self._run_applescript(script)
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

        self._run_applescript(script)
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
        # Get title before deletion for response
        try:
            todo = self.get_todo(uuid)
            title = todo.title
        except ClientError:
            title = uuid

        script = f'''
        tell application "Things3"
            set theToDo to (to do id "{uuid}")
            delete theToDo
        end tell
        '''

        self._run_applescript(script)
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
            when: New when value: today, tomorrow, evening, anytime, someday, or a date (optional)
            deadline: New deadline in YYYY-MM-DD format, or empty string to clear (optional)
            tags: New list of tag titles (replaces existing tags) (optional)
            project: New project UUID to move the todo to (optional). Mutually exclusive with area.
            area: New area UUID to move the todo to (optional, detaches from any project). Mutually exclusive with project.

        Returns:
            Updated Task model

        Raises:
            ClientError: If todo not found or AppleScript fails
            ValueError: If both project and area are supplied
        """
        if project is not None and area is not None:
            raise ValueError("update_todo: pass only one of `project` or `area`, not both")

        # Verify todo exists first
        self.get_todo(uuid)

        # Build property updates
        updates = []

        if title is not None:
            escaped_title = self._escape_applescript_string(title)
            updates.append(f'set name of theToDo to "{escaped_title}"')

        if notes is not None:
            escaped_notes = self._escape_applescript_string(notes)
            updates.append(f'set notes of theToDo to "{escaped_notes}"')

        if deadline is not None:
            if deadline == "":
                updates.append('set due date of theToDo to missing value')
            else:
                as_date = self._iso_to_applescript_date(deadline)
                updates.append(f'set due date of theToDo to date "{as_date}"')

        if tags is not None:
            tag_str = ", ".join(tags)
            escaped_tags = self._escape_applescript_string(tag_str)
            updates.append(f'set tag names of theToDo to "{escaped_tags}"')

        if project is not None:
            # Reassign the todo to a different project. Things AppleScript
            # exposes this via `set project of theToDo to project id "<uuid>"`.
            updates.append(f'set project of theToDo to project id "{project}"')

        if area is not None:
            # Reassign the todo to a different area (detaches from any project).
            # Things AppleScript: `set area of theToDo to area id "<uuid>"`.
            updates.append(f'set area of theToDo to area id "{area}"')

        if updates:
            updates_str = "\n            ".join(updates)
            script = f'''
            tell application "Things3"
                set theToDo to (to do id "{uuid}")
                {updates_str}
            end tell
            '''
            self._run_applescript(script)

        # Handle 'when' by moving to appropriate list
        if when is not None:
            if when == 'today':
                list_name = "Today"
            elif when == 'tomorrow':
                list_name = "Tomorrow"
            elif when == 'evening':
                list_name = "Evening"
            elif when == 'anytime':
                list_name = "Anytime"
            elif when == 'someday':
                list_name = "Someday"
            elif when == 'inbox':
                list_name = "Inbox"
            elif when == '':
                # Clear activation date
                schedule_script = f'''
                tell application "Things3"
                    set theToDo to (to do id "{uuid}")
                    set activation date of theToDo to missing value
                end tell
                '''
                self._run_applescript(schedule_script)
                return self.get_todo(uuid)
            else:
                # Assume it's a date - use schedule command
                as_date = self._iso_to_applescript_date(when)
                schedule_script = f'''
                tell application "Things3"
                    schedule (to do id "{uuid}") for date "{as_date}"
                end tell
                '''
                self._run_applescript(schedule_script)
                return self.get_todo(uuid)

            move_script = f'''
            tell application "Things3"
                set theToDo to (to do id "{uuid}")
                move theToDo to list "{list_name}"
            end tell
            '''
            self._run_applescript(move_script)

        return self.get_todo(uuid)

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
        project_id = self._run_applescript(script)

        if when == 'someday':
            move_script = f'''
            tell application "Things3"
                move project id "{project_id}" to list "Someday"
            end tell
            '''
            self._run_applescript(move_script)

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
            tags: New list of tag titles (replaces existing tags) (optional)

        Returns:
            Updated Project model

        Raises:
            ClientError: If project not found or AppleScript fails
        """
        # Verify project exists first
        self.get_project(uuid)

        # Build property updates
        updates = []

        if title is not None:
            escaped_title = self._escape_applescript_string(title)
            updates.append(f'set name of theProject to "{escaped_title}"')

        if notes is not None:
            escaped_notes = self._escape_applescript_string(notes)
            updates.append(f'set notes of theProject to "{escaped_notes}"')

        if deadline is not None:
            if deadline == "":
                updates.append('set due date of theProject to missing value')
            else:
                as_date = self._iso_to_applescript_date(deadline)
                updates.append(f'set due date of theProject to date "{as_date}"')

        if tags is not None:
            tag_str = ", ".join(tags)
            escaped_tags = self._escape_applescript_string(tag_str)
            updates.append(f'set tag names of theProject to "{escaped_tags}"')

        if updates:
            updates_str = "\n            ".join(updates)
            script = f'''
            tell application "Things3"
                set theProject to project id "{uuid}"
                {updates_str}
            end tell
            '''
            self._run_applescript(script)

        # Handle area assignment
        if area is not None:
            if area == "":
                # Remove from area
                area_script = f'''
                tell application "Things3"
                    set theProject to project id "{uuid}"
                    set area of theProject to missing value
                end tell
                '''
            else:
                area_script = f'''
                tell application "Things3"
                    set theProject to project id "{uuid}"
                    set area of theProject to area id "{area}"
                end tell
                '''
            self._run_applescript(area_script)

        # Handle 'when' by moving to appropriate list
        if when is not None:
            if when == 'anytime':
                list_name = "Anytime"
            elif when == 'someday':
                list_name = "Someday"
            else:
                list_name = "Anytime"  # Default

            move_script = f'''
            tell application "Things3"
                move project id "{uuid}" to list "{list_name}"
            end tell
            '''
            self._run_applescript(move_script)

        return self.get_project(uuid)

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


def get_client() -> ThingsClient:
    """Get or create the global Things client instance."""
    global _client
    if _client is None:
        _client = ThingsClient()
    return _client
