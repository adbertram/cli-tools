"""CourseCraft client using airtable CLI for API access."""
import json
import subprocess
from typing import Dict, List, Optional, Any

from .config import get_config


class ClientError(Exception):
    """Custom exception for CourseCraft errors."""
    pass


class CourseCraftClient:
    """Client for interacting with CourseCraft Airtable base via airtable CLI."""

    def __init__(self):
        """Initialize CourseCraft client from configuration."""
        self.config = get_config()
        self.base_id = self.config.airtable_base_id

        if not self.base_id:
            raise ClientError(
                "Missing AIRTABLE_BASE_ID. Check .env file."
            )

        # Verify airtable CLI is available
        if not self._check_airtable_cli():
            raise ClientError(
                "airtable CLI is not installed or not in PATH. "
                "Install it from ~/Dropbox/GitRepos/cli-tools/airtable"
            )

    def _check_airtable_cli(self) -> bool:
        """Check if airtable CLI is available."""
        try:
            result = subprocess.run(
                ["airtable", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _run_airtable_command(self, args: List[str]) -> Dict:
        """
        Run an airtable CLI command and return parsed output.

        Args:
            args: Command arguments (excluding 'airtable')

        Returns:
            Parsed JSON response

        Raises:
            ClientError: If command fails
        """
        full_args = ["airtable"] + args

        try:
            result = subprocess.run(
                full_args,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                raise ClientError(f"airtable CLI error: {result.stderr.strip()}")

            # Parse JSON from output (skip any status lines)
            output_lines = result.stdout.strip().split('\n')
            json_output = None

            for line in output_lines:
                line = line.strip()
                if line.startswith('{') or line.startswith('['):
                    try:
                        json_output = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue

            if json_output is None:
                # If no JSON found, try parsing entire output
                try:
                    json_output = json.loads(result.stdout.strip())
                except json.JSONDecodeError:
                    raise ClientError(f"Could not parse airtable CLI output: {result.stdout}")

            return json_output

        except subprocess.TimeoutExpired:
            raise ClientError("airtable CLI command timed out")
        except Exception as e:
            raise ClientError(f"Error running airtable CLI: {e}")

    def _extract_record_id(self, response: Dict) -> str:
        """
        Extract record ID from airtable CLI response.

        Args:
            response: Response dict from airtable CLI

        Returns:
            Record ID string

        Raises:
            ClientError: If ID cannot be extracted
        """
        record_id = response.get('id')
        if not record_id:
            raise ClientError(f"Could not extract record ID from response: {response}")
        return record_id

    def create_record(
        self,
        table: str,
        fields: Dict[str, Any]
    ) -> str:
        """
        Create a record in an Airtable table.

        Args:
            table: Table name
            fields: Dict of field names to values

        Returns:
            Created record ID

        Raises:
            ClientError: If creation fails
        """
        args = ["records", "create", table, "--base", self.base_id]

        # Add fields as arguments
        for field_name, value in fields.items():
            if value is not None and value != "":
                # Handle linked records (arrays)
                if isinstance(value, list):
                    value = json.dumps(value)
                args.append(f"{field_name}={value}")

        response = self._run_airtable_command(args)
        return self._extract_record_id(response)

    def list_records(
        self,
        table: str,
        filter_formula: Optional[str] = None
    ) -> List[Dict]:
        """
        List records from a table.

        Args:
            table: Table name
            filter_formula: Optional Airtable filter formula

        Returns:
            List of record dicts

        Raises:
            ClientError: If listing fails
        """
        args = ["records", "list", table, "--base", self.base_id]

        if filter_formula:
            args.extend(["--formula", filter_formula])

        response = self._run_airtable_command(args)

        # Response format: {"records": [...]}
        return response.get("records", [])

    def resolve_course_id(self, course_identifier: str) -> str:
        """
        Resolve a course identifier to a record ID.
        Accepts either a record ID (recXXX) or a Course ID slug.

        Args:
            course_identifier: Either record ID or Course ID slug

        Returns:
            Record ID

        Raises:
            ClientError: If course cannot be found (includes suggestions)
        """
        # If it already looks like a record ID, return it
        if course_identifier.startswith('rec'):
            return course_identifier

        # Otherwise, search for the course by Course ID field
        filter_formula = f"{{Course ID}}='{course_identifier}'"
        records = self.list_records("Courses", filter_formula)

        if not records:
            # Get all courses to provide suggestions
            all_courses = self.list_records("Courses")
            suggestions = []
            for course in all_courses:
                fields = course.get("fields", {})
                slug = fields.get("Course ID", "")
                name = fields.get("Name", "")
                if slug:
                    suggestions.append(f"  - {slug} ({name})")

            msg = f"Course '{course_identifier}' not found."
            if suggestions:
                msg += "\n\nAvailable courses:\n" + "\n".join(suggestions)
            raise ClientError(msg)

        return records[0]['id']

    def resolve_environment_id(self, environment_identifier: str) -> str:
        """
        Resolve a demo environment identifier to a record ID.
        Accepts a record ID, Environment ID slug, or exact Name.

        Args:
            environment_identifier: Record ID, Environment ID, or Name

        Returns:
            Record ID

        Raises:
            ClientError: If environment cannot be found
        """
        if environment_identifier.startswith('rec'):
            return environment_identifier

        escaped_identifier = environment_identifier.replace("'", "\\'")
        filter_formula = (
            f"OR({{Environment ID}}='{escaped_identifier}', "
            f"{{Name}}='{escaped_identifier}')"
        )
        records = self.list_records("Demo Environments", filter_formula)

        if not records:
            all_environments = self.list_records("Demo Environments")
            suggestions = []
            for environment in all_environments:
                fields = environment.get("fields", {})
                environment_id = fields.get("Environment ID", "")
                name = fields.get("Name", "")
                if environment_id:
                    suggestions.append(f"  - {environment_id} ({name})")

            msg = f"Demo environment '{environment_identifier}' not found."
            if suggestions:
                msg += "\n\nAvailable demo environments:\n" + "\n".join(suggestions)
            raise ClientError(msg)

        return records[0]['id']

    def check_course_exists(self, name: str) -> Optional[str]:
        """
        Check if a course with the given name already exists.

        Args:
            name: Course name to check

        Returns:
            Record ID if exists, None otherwise
        """
        # Escape single quotes in the name for the formula
        escaped_name = name.replace("'", "\\'")
        filter_formula = f"{{Name}}='{escaped_name}'"
        records = self.list_records("Courses", filter_formula)
        return records[0]['id'] if records else None

    def check_module_exists(self, name: str, course_record_id: str) -> Optional[str]:
        """
        Check if a module with the given name already exists in a course.

        Args:
            name: Module name to check
            course_record_id: Parent course record ID

        Returns:
            Record ID if exists, None otherwise
        """
        escaped_name = name.replace("'", "\\'")
        # Use the Course Record ID lookup field for filtering
        filter_formula = f"AND({{Name}}='{escaped_name}', {{Course Record ID}}='{course_record_id}')"
        records = self.list_records("Modules", filter_formula)
        return records[0]['id'] if records else None

    def check_clip_exists(self, name: str, module_record_id: str) -> Optional[str]:
        """
        Check if a clip with the given name already exists in a module.

        Args:
            name: Clip name to check
            module_record_id: Parent module record ID

        Returns:
            Record ID if exists, None otherwise
        """
        escaped_name = name.replace("'", "\\'")
        # Use the Module Record ID lookup field for filtering
        filter_formula = f"AND({{Name}}='{escaped_name}', {{Module Record ID}}='{module_record_id}')"
        records = self.list_records("Clips", filter_formula)
        return records[0]['id'] if records else None

    def resolve_module_id(self, module_identifier: str, course_identifier: Optional[str] = None) -> str:
        """
        Resolve a module identifier to a record ID.
        Accepts a record ID (recXXX), ID field pattern (M1, M2), or partial name match.

        Args:
            module_identifier: Record ID, ID pattern, or name to search
            course_identifier: Optional course to scope the search

        Returns:
            Record ID

        Raises:
            ClientError: If module cannot be found (includes suggestions)
        """
        # If it already looks like a record ID, return it
        if module_identifier.startswith('rec'):
            return module_identifier

        # Build filter formula
        course_record_id = None
        if course_identifier:
            course_record_id = self.resolve_course_id(course_identifier)

        # Search by ID field (exact match or starts with)
        escaped_id = module_identifier.replace("'", "\\'")
        if course_record_id:
            filter_formula = f"AND(OR({{ID}}='{escaped_id}', FIND('{escaped_id}', {{ID}})=1), {{Course Record ID}}='{course_record_id}')"
        else:
            filter_formula = f"OR({{ID}}='{escaped_id}', FIND('{escaped_id}', {{ID}})=1)"

        records = self.list_records("Modules", filter_formula)

        if records:
            # Sort by Order to get consistent results
            records.sort(key=lambda r: r.get("fields", {}).get("Order", 999))
            return records[0]['id']

        # Not found - get all modules to provide suggestions
        if course_record_id:
            all_modules = self.list_records("Modules", f"{{Course Record ID}}='{course_record_id}'")
        else:
            all_modules = self.list_records("Modules")

        suggestions = []
        for module in sorted(all_modules, key=lambda m: m.get("fields", {}).get("Order", 999)):
            fields = module.get("fields", {})
            mid = fields.get("ID", "")
            name = fields.get("Name", "")
            if mid:
                suggestions.append(f"  - {mid}")

        msg = f"Module '{module_identifier}' not found."
        if suggestions:
            msg += "\n\nAvailable modules:\n" + "\n".join(suggestions)
        raise ClientError(msg)

    def resolve_clip_id(self, clip_identifier: str, course_identifier: Optional[str] = None) -> str:
        """
        Resolve a clip identifier to a record ID.
        Accepts a record ID (recXXX), ID field pattern (M1C1, M1C2), or partial name match.

        Args:
            clip_identifier: Record ID, ID pattern, or name to search
            course_identifier: Optional course to scope the search

        Returns:
            Record ID

        Raises:
            ClientError: If clip cannot be found (includes suggestions)
        """
        # If it already looks like a record ID, return it
        if clip_identifier.startswith('rec'):
            return clip_identifier

        # Resolve course if specified
        course_record_id = None
        if course_identifier:
            course_record_id = self.resolve_course_id(course_identifier)

        # Search by ID field (exact match or starts with)
        # Note: Can't filter by Course directly in formula (linked record array)
        # So we fetch matching IDs then filter client-side
        escaped_id = clip_identifier.replace("'", "\\'")
        filter_formula = f"OR({{ID}}='{escaped_id}', FIND('{escaped_id}', {{ID}})=1)"

        records = self.list_records("Clips", filter_formula)

        # Filter by course if specified (Course is a linked record array)
        if course_record_id and records:
            records = [r for r in records if course_record_id in (r.get("fields", {}).get("Course") or [])]

        if records:
            # Sort by module order then clip order to get consistent results
            records.sort(key=lambda r: (
                r.get("fields", {}).get("Module Number", [999])[0] if r.get("fields", {}).get("Module Number") else 999,
                r.get("fields", {}).get("Order", 999)
            ))
            return records[0]['id']

        # Not found - get all clips to provide suggestions
        # Fetch all clips and filter client-side if course specified
        all_clips = self.list_records("Clips")
        if course_record_id:
            all_clips = [c for c in all_clips if course_record_id in (c.get("fields", {}).get("Course") or [])]

        suggestions = []
        for clip in sorted(all_clips, key=lambda c: (
            c.get("fields", {}).get("Module Number", [999])[0] if c.get("fields", {}).get("Module Number") else 999,
            c.get("fields", {}).get("Order", 999)
        )):
            fields = clip.get("fields", {})
            cid = fields.get("ID", "")
            if cid:
                suggestions.append(f"  - {cid}")

        msg = f"Clip '{clip_identifier}' not found."
        if suggestions:
            msg += "\n\nAvailable clips:\n" + "\n".join(suggestions)
        raise ClientError(msg)

    def check_demo_exists(self, name: str, clip_record_id: str) -> Optional[str]:
        """
        Check if a demo with the given name already exists in a clip.

        Note: Requires 'Clip Record ID' lookup field in Demos table.
        If not present, this check will not work correctly.

        Args:
            name: Demo name to check
            clip_record_id: Parent clip record ID

        Returns:
            Record ID if exists, None otherwise
        """
        escaped_name = name.replace("'", "\\'")
        # Use the Clip Record ID lookup field for filtering
        filter_formula = f"AND({{Name}}='{escaped_name}', {{Clip Record ID}}='{clip_record_id}')"
        records = self.list_records("Demos", filter_formula)
        return records[0]['id'] if records else None

    def check_slide_exists(self, clip_record_id: str, template_record_id: Optional[str] = None) -> Optional[str]:
        """
        Check if a slide already exists in a clip (optionally with same template).

        Note: Requires 'Clip Record ID' lookup field in Slides table.
        If not present, this check will not work correctly.

        Args:
            clip_record_id: Parent clip record ID
            template_record_id: Optional template record ID to match

        Returns:
            Record ID if exists, None otherwise
        """
        if template_record_id:
            # Use Clip Record ID and Template Record ID lookup fields
            filter_formula = f"AND({{Clip Record ID}}='{clip_record_id}', {{Template Record ID}}='{template_record_id}')"
        else:
            # Just check clip without template
            filter_formula = f"{{Clip Record ID}}='{clip_record_id}'"
        records = self.list_records("Slides", filter_formula)
        return records[0]['id'] if records else None

    def delete_record(self, table: str, record_id: str) -> bool:
        """
        Delete a record from an Airtable table.

        Args:
            table: Table name
            record_id: Record ID to delete

        Returns:
            True if deletion succeeded

        Raises:
            ClientError: If deletion fails
        """
        args = ["records", "delete", table, record_id, "--base", self.base_id, "--yes"]

        full_args = ["airtable"] + args
        try:
            result = subprocess.run(
                full_args,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                raise ClientError(f"Failed to delete record {record_id}: {result.stderr.strip()}")

            return True

        except subprocess.TimeoutExpired:
            raise ClientError("airtable CLI command timed out")
        except Exception as e:
            raise ClientError(f"Error deleting record: {e}")

    def get_modules_by_course(self, course_record_id: str) -> List[Dict]:
        """
        Get all modules belonging to a course.

        Args:
            course_record_id: Course record ID

        Returns:
            List of module record dicts
        """
        filter_formula = f"{{Course Record ID}}='{course_record_id}'"
        return self.list_records("Modules", filter_formula)

    def get_clips_by_module(self, module_record_id: str) -> List[Dict]:
        """
        Get all clips belonging to a module.

        Args:
            module_record_id: Module record ID

        Returns:
            List of clip record dicts
        """
        filter_formula = f"{{Module Record ID}}='{module_record_id}'"
        return self.list_records("Clips", filter_formula)

    def get_demos_by_clip(self, clip_record_id: str) -> List[Dict]:
        """
        Get all demos belonging to a clip.

        Args:
            clip_record_id: Clip record ID

        Returns:
            List of demo record dicts
        """
        filter_formula = f"{{Clip Record ID}}='{clip_record_id}'"
        return self.list_records("Demos", filter_formula)

    def get_slides_by_clip(self, clip_record_id: str) -> List[Dict]:
        """
        Get all slides belonging to a clip.

        Args:
            clip_record_id: Clip record ID

        Returns:
            List of slide record dicts
        """
        filter_formula = f"{{Clip Record ID}}='{clip_record_id}'"
        return self.list_records("Slides", filter_formula)

    def get_demos_by_module(self, module_record_id: str) -> List[Dict]:
        """
        Get all demos for all clips in a module.

        Args:
            module_record_id: Module record ID

        Returns:
            List of demo record dicts
        """
        clips = self.get_clips_by_module(module_record_id)
        demos = []
        for clip in clips:
            clip_demos = self.get_demos_by_clip(clip['id'])
            demos.extend(clip_demos)
        return demos

    def get_demos_by_course(self, course_identifier: str) -> List[Dict]:
        """
        Get all demos for a course.

        Args:
            course_identifier: Course slug or record ID

        Returns:
            List of demo record dicts
        """
        course_id = self.resolve_course_id(course_identifier)
        modules = self.get_modules_by_course(course_id)
        demos = []
        for module in modules:
            module_demos = self.get_demos_by_module(module['id'])
            demos.extend(module_demos)
        return demos

    def get_slides_by_module(self, module_record_id: str) -> List[Dict]:
        """
        Get all slides for all clips in a module.

        Args:
            module_record_id: Module record ID

        Returns:
            List of slide record dicts
        """
        clips = self.get_clips_by_module(module_record_id)
        slides = []
        for clip in clips:
            clip_slides = self.get_slides_by_clip(clip['id'])
            slides.extend(clip_slides)
        return slides

    def get_slides_by_course(self, course_identifier: str) -> List[Dict]:
        """
        Get all slides for a course.

        Args:
            course_identifier: Course slug or record ID

        Returns:
            List of slide record dicts
        """
        course_id = self.resolve_course_id(course_identifier)
        modules = self.get_modules_by_course(course_id)
        slides = []
        for module in modules:
            module_slides = self.get_slides_by_module(module['id'])
            slides.extend(module_slides)
        return slides

    def get_record(self, table: str, record_id: str) -> Optional[Dict]:
        """
        Get a single record by ID.

        Args:
            table: Table name
            record_id: Record ID

        Returns:
            Record dict or None if not found

        Raises:
            ClientError: If request fails
        """
        args = ["records", "get", table, record_id, "--base", self.base_id]
        try:
            return self._run_airtable_command(args)
        except ClientError as e:
            if "not found" in str(e).lower():
                return None
            raise

    def update_record(
        self,
        table: str,
        record_id: str,
        fields: Dict[str, Any]
    ) -> Dict:
        """
        Update a record in an Airtable table.

        Args:
            table: Table name
            record_id: Record ID to update
            fields: Dict of field names to values

        Returns:
            Updated record dict

        Raises:
            ClientError: If update fails
        """
        args = ["records", "update", table, record_id, "--base", self.base_id, "--typecast"]

        # Add fields as arguments
        for field_name, value in fields.items():
            if value is not None:
                # Handle linked records (arrays)
                if isinstance(value, list):
                    value = json.dumps(value)
                # Handle booleans - lowercase for airtable
                elif isinstance(value, bool):
                    value = "true" if value else "false"
                args.append(f"{field_name}={value}")

        return self._run_airtable_command(args)


# Module-level client instance - singleton pattern
_client: Optional[CourseCraftClient] = None


def get_client() -> CourseCraftClient:
    """Get or create the global CourseCraft client instance."""
    global _client
    if _client is None:
        _client = CourseCraftClient()
    return _client
