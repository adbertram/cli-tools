"""CourseCraft client using airtable CLI for API access."""
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Any

from .artifact_versions import plan_record_update
from .config import get_config
from .filter_translator import escape_value


AIRTABLE_CLI_COMMAND_TIMEOUT_SECONDS = 45

# Airtable's REST API returns at most 100 records per page and hands back an
# ``offset`` token to fetch the next page. ``list_records`` requests one page at a
# time at this size and follows the returned offset until Airtable stops issuing
# one, so every matching record is returned regardless of table size. Requesting
# exactly one API page per call keeps the airtable CLI's offset reliable (it
# exposes the upstream offset whenever a full page had more after it).
AIRTABLE_PAGE_SIZE = 100

# Airtable returns these error markers when a record ID does not resolve. The
# verification read after a write relies on detecting a missing record, so the
# match must cover Airtable's machine codes (NOT_FOUND, MODEL_ID_NOT_FOUND) as
# well as the human-readable "not found" phrasing.
_RECORD_NOT_FOUND_MARKERS = (
    "not found",
    "not_found",
    "(404)",
)

# Airtable's ``richText`` long-text fields are not byte-exact stores. Airtable
# parses the written text as Markdown and re-serializes it, so the persisted
# bytes can differ from the bytes that were sent. Measured against base
# app9uzzru5KZOImYQ on 2026-07-27 with a scratch Demos record:
#
#   sent                                    persisted
#   ------------------------------------    ------------------------------------
#   __$operation 2 ... __$operation 4       **$operation 2 ... **$operation 4
#   __single pair__                         **single pair**
#   module_brainstorming_outline            module_brainstorming\_outline
#   *emphasis*                              _emphasis_
#   "text   " (trailing spaces)             "text\n" (spaces dropped)
#   "text" (no trailing newline)            "text\n"
#
# A ``multilineText`` field in the same record round-tripped every one of those
# payloads byte-for-byte and gained no trailing newline. The corruption is
# therefore a property of the ``richText`` field type, not of this CLI.
#
# Measured live on 2026-08-07 against the Feedback table: a ``multilineText``
# value sent WITH a trailing newline (9147 chars ending in "\n") persisted with
# that trailing newline stripped (9146 chars). Airtable canonicalizes the
# trailing edge of a ``multilineText`` value by stripping trailing
# whitespace/newlines. That removes no content character.
#
# The write self-verifier must report every interior difference as a failed
# write. Only two trailing-edge normalizations are tolerated, because neither
# touches a single content character:
#   * the one trailing newline Airtable APPENDS to a ``richText`` value as a
#     storage terminator, and
#   * the trailing whitespace/newlines Airtable STRIPS from a ``multilineText``
#     value.
# Nothing else is folded away.
_RICH_TEXT_CAUSE_HINT = (
    "A long-text mismatch of Markdown punctuation (for example '__' -> '**', "
    "'_x_' <-> '*x*', or an added backslash escape) means the target field is an "
    "Airtable 'richText' field. Airtable re-serializes Markdown in a richText "
    "field, so it cannot store text containing '__', '*', or '_' byte-exactly. "
    "Run `airtable fields get <table> <field> --base <base>` to confirm the type, "
    "then convert the field to 'Long text' with rich text formatting turned OFF "
    "in the Airtable UI. The Airtable Meta API cannot change a field's type."
)

# CourseCraft richText fields in base app9uzzru5KZOImYQ as of 2026-07-27:
# Demos.Script, Clips.'Learning Objectives', Modules.'Learning Objectives',
# Modules.'Brainstorming Outline', Courses.'Brainstorming Notes'.

# Number of characters of context shown either side of the first differing
# offset when a long-text mismatch is reported. A demo Script is several
# kilobytes, so the error names the exact offset instead of dumping both values.
_MISMATCH_CONTEXT_CHARS = 60

# Values longer than this are reported as a bounded diff rather than in full.
_MISMATCH_FULL_REPR_LIMIT = 200

_COURSE_DISABLE_FIELDS = {"Disabled", "Disabled Notes"}
_COURSE_SCOPED_TABLES = {"Courses", "Modules", "Clips", "Demos", "Slides", "Feedback"}


def _resolve_airtable_binary() -> Optional[str]:
    """Absolute path to the ``airtable`` CLI binary, or ``None`` when absent.

    This is a pure PATH lookup (``shutil.which``): it never starts a process,
    so it can never time out. It deliberately replaces an older
    ``airtable --version`` probe whose uv-tool Python cold start could exceed a
    short subprocess timeout under load — e.g. batched validator runs that spawn
    several ``coursecraft`` + ``airtable`` processes at once — and be misreported
    as the binary being "not installed" even though it is present on PATH. A
    PATH lookup makes that false negative impossible.

    ``~/.local/bin`` (where uv installs CLI shims) is forced onto the search
    path so an inherited or minimal environment cannot hide a present binary.
    """
    local_bin = str(Path.home() / ".local" / "bin")
    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    if local_bin not in path_parts:
        path_parts.insert(0, local_bin)
    search_path = os.pathsep.join(part for part in path_parts if part)
    return shutil.which("airtable", path=search_path)


class ClientError(Exception):
    """Custom exception for CourseCraft errors."""
    pass


class WriteVerificationError(ClientError):
    """Raised when a create/update write cannot be confirmed as persisted.

    This is the loud failure for the phantom-success hazard: a write that
    returned an ID (or a PATCH response) but cannot be re-read from Airtable,
    or whose persisted fields do not match what was sent. It is a ``ClientError``
    subclass so existing command handlers surface it and exit non-zero.

    ``mismatched_fields`` names exactly the field(s) that failed to verify.
    Empty (the default) means no field-scoped attribution is available because
    the record could not be re-read at all or the raise site predates this
    attribute.
    """

    def __init__(self, message: str, *, mismatched_fields: FrozenSet[str] = frozenset()):
        super().__init__(message)
        self.mismatched_fields = mismatched_fields


def _airtable_field_arg(field_name: str, value: Any) -> str:
    """Serialize a field into the airtable CLI's ``Field=value`` token.

    The airtable ``records create``/``update`` commands eagerly ``json.loads``
    each value and only fall back to a raw string on a JSON parse error. That
    means a Python string whose content is itself valid JSON (e.g. a
    ``Placeholders`` blob, or a digit-only text value) would be reinterpreted as
    a list/number and either rejected by a text field or stored with the wrong
    type. To preserve the exact string, wrap such values with ``json.dumps`` so
    the CLI parses the JSON string literal straight back to the original string.

    Lists are JSON-encoded (linked records / attachment arrays) and booleans are
    lowercased, matching Airtable's expectations.
    """
    if isinstance(value, bool):
        encoded = "true" if value else "false"
    elif isinstance(value, list):
        encoded = json.dumps(value)
    elif isinstance(value, str):
        try:
            json.loads(value)
        except json.JSONDecodeError:
            encoded = value
        else:
            # Value looks like JSON to the airtable CLI; wrap it so it survives
            # as the original string instead of being reparsed into a structure.
            encoded = json.dumps(value)
    else:
        encoded = value
    return f"{field_name}={encoded}"


class CourseCraftClient:
    """Client for interacting with CourseCraft Airtable base via airtable CLI."""

    def __init__(self):
        """Initialize CourseCraft client from configuration."""
        self.config = get_config()
        self.base_id = self.config.airtable_base_id
        self._field_metadata_cache: Dict[str, Dict[str, Dict[str, Any]]] = {}

        if not self.base_id:
            raise ClientError(
                "Missing AIRTABLE_BASE_ID. Check .env file."
            )

        # Verify airtable CLI is available
        if not self._check_airtable_cli():
            raise ClientError(
                "airtable CLI is not installed or not in PATH. "
                "Install it with `scripts/install-cli-tool.sh airtable` from the cli-tools repo root."
            )

    def _check_airtable_cli(self) -> bool:
        """Return ``True`` when the airtable CLI binary is resolvable on PATH.

        Uses a pure PATH lookup (see :func:`_resolve_airtable_binary`) instead of
        spawning ``airtable --version`` so a present-but-slow-to-start binary is
        never falsely reported as missing. Any genuinely transient runtime
        failure surfaces later with its real stderr via
        :meth:`_run_airtable_command`, not as the misleading "not installed"
        message.
        """
        return _resolve_airtable_binary() is not None

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
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=AIRTABLE_CLI_COMMAND_TIMEOUT_SECONDS,
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
            raise ClientError(f"airtable CLI command timed out after {AIRTABLE_CLI_COMMAND_TIMEOUT_SECONDS}s")
        except Exception as e:
            raise ClientError(f"Error running airtable CLI: {e}")

    def rename_field(self, table: str, current_name: str, new_name: str) -> Dict:
        """Rename one Airtable field and verify the schema read-back."""
        fields = self._run_airtable_command(
            ["fields", "list", table, "--base", self.base_id]
        )
        if not isinstance(fields, list):
            raise ClientError(
                f"Unexpected field-list response for table {table}: {fields}"
            )

        current = [field for field in fields if field.get("name") == current_name]
        if len(current) != 1:
            raise ClientError(
                f"Expected exactly one field named '{current_name}' in {table}; "
                f"found {len(current)}."
            )
        if any(field.get("name") == new_name for field in fields):
            raise ClientError(f"Field '{new_name}' already exists in {table}.")

        field_id = current[0].get("id")
        if not isinstance(field_id, str) or not field_id.startswith("fld"):
            raise ClientError(
                f"Field metadata for '{current_name}' did not include a valid field ID."
            )

        self._run_airtable_command(
            [
                "fields",
                "update",
                table,
                field_id,
                "--base",
                self.base_id,
                "--name",
                new_name,
            ]
        )
        verified = self._run_airtable_command(
            ["fields", "get", table, field_id, "--base", self.base_id]
        )
        if verified.get("name") != new_name:
            raise WriteVerificationError(
                f"Field rename in {table} did not persist: expected '{new_name}', "
                f"read back {verified.get('name')!r}.",
                mismatched_fields=frozenset({new_name}),
            )
        return verified

    def _field_storage_metadata(self, table: str) -> Dict[str, Dict[str, Any]]:
        """Return exact Airtable field metadata keyed by field name."""
        cached = self._field_metadata_cache.get(table)
        if cached is not None:
            return cached

        fields = self._run_airtable_command(
            ["fields", "list", table, "--base", self.base_id]
        )
        if not isinstance(fields, list):
            raise ClientError(
                f"Unexpected field-list response for table {table}: {fields}"
            )
        metadata: Dict[str, Dict[str, Any]] = {}
        for field in fields:
            if not isinstance(field, dict):
                raise ClientError(
                    f"Field metadata for table {table} must contain objects."
                )
            name = field.get("name")
            field_type = field.get("type")
            if not isinstance(name, str) or not name:
                raise ClientError(
                    f"Field metadata for table {table} is missing a field name."
                )
            if not isinstance(field_type, str) or not field_type:
                raise ClientError(
                    f"Field metadata for {table}.{name} is missing its exact type."
                )
            if name in metadata:
                raise ClientError(f"Duplicate field metadata for {table}.{name}.")
            metadata[name] = field

        self._field_metadata_cache[table] = metadata
        return metadata

    def _planning_fields(
        self,
        table: str,
        current_fields: Dict[str, Any],
        proposed_fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add read-only discriminator fields needed by the pre-write planner."""
        planning_fields = dict(current_fields)
        if table != "Slides" or "Template" not in proposed_fields:
            return planning_fields

        template_ids = proposed_fields.get("Template")
        if not isinstance(template_ids, list) or len(template_ids) != 1:
            planning_fields.pop("Template Name", None)
            return planning_fields
        template = self.get_record("Slide Templates", template_ids[0])
        template_name = (template or {}).get("fields", {}).get("Name")
        if not isinstance(template_name, str) or not template_name.strip():
            raise ClientError(
                f"Slide template {template_ids[0]!r} has no exact Name discriminator."
            )
        planning_fields["Template Name"] = [template_name]
        return planning_fields

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

    @staticmethod
    def _verifiable_field_value(value: Any) -> bool:
        """Return whether a sent field value can be compared after a write.

        Airtable normalizes many field types on write (linked-record arrays are
        re-ordered/expanded, numbers are coerced under ``--typecast``, computed
        fields are derived, attachments gain server metadata, and an unchecked
        checkbox is returned as an absent field rather than ``False``). Plain
        text/number scalars and checkbox booleans can still be verified with
        their documented round-trip forms; normalized collections are skipped.
        """
        return isinstance(value, (str, int, float, bool))

    @staticmethod
    def _first_difference_index(sent: str, actual: str) -> int:
        """Index of the first character where two strings differ.

        Returns the length of the shorter string when one is a prefix of the
        other (a truncated or extended persist).
        """
        for index, (sent_char, actual_char) in enumerate(zip(sent, actual)):
            if sent_char != actual_char:
                return index
        return min(len(sent), len(actual))

    @staticmethod
    def _describe_mismatch(field_name: str, sent_value: Any, actual: Any) -> str:
        """Describe one field mismatch without dumping a multi-kilobyte value.

        Short values are reported in full. For long text, the description names
        both lengths, the offset of the first differing character, and a bounded
        window of each side around that offset, so the exact corrupted bytes are
        visible in the error without printing the whole script.
        """
        if (
            not isinstance(sent_value, str)
            or not isinstance(actual, str)
            or (
                len(sent_value) <= _MISMATCH_FULL_REPR_LIMIT
                and len(actual) <= _MISMATCH_FULL_REPR_LIMIT
            )
        ):
            return f"{field_name!r}: sent {sent_value!r}, persisted {actual!r}"

        offset = CourseCraftClient._first_difference_index(sent_value, actual)
        start = max(0, offset - _MISMATCH_CONTEXT_CHARS)
        end = offset + _MISMATCH_CONTEXT_CHARS
        return (
            f"{field_name!r}: sent {len(sent_value)} chars, persisted "
            f"{len(actual)} chars; first difference at offset {offset}; "
            f"sent {sent_value[start:end]!r} vs persisted {actual[start:end]!r}"
        )

    @staticmethod
    def _parse_iso_datetime(value: str) -> Optional[datetime]:
        """Parse an ISO-8601 datetime string, or return ``None`` if it is not one.

        Airtable persists dateTime fields in UTC with a trailing ``Z`` and
        millisecond precision (``2026-06-20T19:05:00.000Z``), while callers often
        send the equivalent ``+00:00`` offset form (``2026-06-20T19:05:00+00:00``).
        Both denote the same instant. A trailing ``Z`` is normalized to ``+00:00``
        before parsing so older interpreters (whose ``fromisoformat`` predates
        native ``Z`` support) behave identically to this runtime. A value that is
        not a parseable ISO datetime returns ``None``, so non-date scalars fall
        through to the ordinary mismatch path unchanged.
        """
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith(("Z", "z")):
            candidate = candidate[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None

    @staticmethod
    def _datetime_instants_match(sent_value: Any, actual: Any) -> bool:
        """Return whether both sides are ISO datetimes denoting the same instant.

        ``True`` only when each side parses as an ISO-8601 datetime AND the two
        refer to the same moment in time. This tolerates Airtable's dateTime
        round-trip (``+00:00`` offset sent vs ``.000Z`` persisted) without
        weakening the check: two different instants — or anything that is not a
        datetime on either side — return ``False`` and remain a mismatch.

        Naive and timezone-aware datetimes cannot be compared directly in Python,
        so the comparison is done on the aware-UTC form via ``timestamp()`` only
        when both are aware; if exactly one side carries a tzinfo the instants are
        genuinely ambiguous and are treated as non-matching.
        """
        sent_dt = CourseCraftClient._parse_iso_datetime(str(sent_value))
        actual_dt = CourseCraftClient._parse_iso_datetime(str(actual))
        if sent_dt is None or actual_dt is None:
            return False
        sent_aware = sent_dt.tzinfo is not None
        actual_aware = actual_dt.tzinfo is not None
        if sent_aware != actual_aware:
            # One naive, one aware: the offset is unknown, so the instant cannot
            # be proven equal. Don't tolerate it.
            return False
        if sent_aware:
            return sent_dt.timestamp() == actual_dt.timestamp()
        return sent_dt == actual_dt

    @staticmethod
    def _split_multiselect(sent_value: str) -> List[str]:
        """Split a sent comma-separated multi-select value the way the writer does.

        Multi-select (and any comma-list) fields are sent to Airtable as a single
        comma-separated string (e.g. ``"Databases,Database performance"``); the
        command layer never pre-splits them and ``--typecast`` makes Airtable
        split on commas and trim each option into an array. This mirrors that
        split so the write self-verifier can compare the sent string against the
        persisted array on equal footing: split on ``,``, strip each element, and
        drop empties (a trailing comma or accidental double comma must not invent
        a blank option).
        """
        return [part.strip() for part in sent_value.split(",") if part.strip()]

    @staticmethod
    def _multiselect_values_match(sent_value: Any, actual: Any) -> bool:
        """Return whether a sent comma-string matches a persisted list, order-insensitively.

        Airtable persists a multi-select field written as a comma-separated
        string as a JSON array of the individual options, and it does not
        guarantee the array preserves the sent order. This tolerates exactly that
        string->array round-trip: the sent string is split the same way the
        writer relies on (:meth:`_split_multiselect`), and the two collections
        are compared as order-insensitive multisets.

        Applies only when the sent value is a ``str`` and the persisted value is a
        ``list``. It does NOT weaken real mismatch detection: a dropped option, an
        extra option, or a substituted option makes the sorted collections differ
        and still counts as a mismatch. Non-(str, list) shapes return ``False`` so
        the caller falls through to the ordinary scalar comparison unchanged, and
        a sent list (linked records) is never routed here — those remain skipped
        by :meth:`_verifiable_field_value`.
        """
        if not isinstance(sent_value, str) or not isinstance(actual, list):
            return False
        sent_parts = CourseCraftClient._split_multiselect(sent_value)
        actual_parts = [str(item).strip() for item in actual]
        return sorted(sent_parts) == sorted(actual_parts)

    @staticmethod
    def _persisted_value_matches(sent_value: Any, actual: Any) -> bool:
        """Return whether a persisted scalar matches what was sent.

        Tolerates server-side normalizations that are not genuine content
        changes, without weakening the check for real mismatches:

        * ``--typecast`` number/string coercion: a sent string number can
          persist as a number (or vice versa), so string forms are compared.
        * Multi-select string->array round-trip: a sent comma-separated string
          (``"a,b,c"``) persists as a JSON array (``["a", "b", "c"]``) in
          Airtable's own, possibly-reordered order. Compared as an
          order-insensitive multiset of the split options. See
          ``_multiselect_values_match``.
        * Airtable's dateTime round-trip: a sent UTC offset form
          (``2026-06-20T19:05:00+00:00``) persists as the ``Z``/millisecond form
          (``2026-06-20T19:05:00.000Z``). These denote the same instant, so they
          are compared by instant, not by string. See
          ``_datetime_instants_match``.
        * A single trailing newline that Airtable appends to a ``richText``
          long-text value as its storage terminator. No content character
          changes, so ``"body"`` persisting as ``"body\\n"`` is a match.
        * Trailing whitespace/newlines that Airtable strips from a
          ``multilineText`` value as its trailing-edge canonicalization
          (measured live 2026-08-07 on Feedback.'Attribute Snapshot': sent
          ``"body\\n"`` persisted as ``"body"``). No content character changes,
          so a persisted value equal to the sent value with only its trailing
          whitespace removed is a match.

        Interior Markdown canonicalization is deliberately NOT tolerated.
        Airtable rewrites ``__x__`` to ``**x**``, rewrites ``*x*`` to ``_x_``,
        and backslash-escapes intraword underscores inside a ``richText`` field.
        Those change the stored characters, so they are real corruption and must
        fail the write. See ``_RICH_TEXT_CAUSE_HINT``.

        Every other difference — an interior change, truncation, word
        substitution, a dropped or extra multi-select option, a different
        datetime instant, a leading-whitespace change, and trailing whitespace
        REPLACED by other characters — counts as a mismatch.
        """
        if isinstance(sent_value, bool):
            # Airtable omits an unchecked checkbox instead of returning false.
            # A checked checkbox must still read back as the boolean true.
            return actual is True if sent_value else actual is None or actual is False
        if sent_value == "" and actual is None:
            return True
        if actual == sent_value:
            return True
        # Multi-select fields are sent as one comma-separated string and persist
        # as a JSON array of the split options (order not guaranteed). Tolerate
        # exactly that string->array round-trip while a dropped/extra/substituted
        # option still mismatches.
        if CourseCraftClient._multiselect_values_match(sent_value, actual):
            return True
        sent_str = str(sent_value)
        actual_str = str(actual)
        if sent_str == actual_str:
            return True
        # Airtable appends exactly one newline to a richText value as its
        # storage terminator. That adds no content character. An extra blank
        # line or any interior change is a real mutation and still mismatches.
        if actual_str == sent_str + "\n":
            return True
        # Airtable strips trailing whitespace/newlines from a multilineText
        # value as its trailing-edge canonicalization. That removes no content
        # character. When the sent value has no trailing whitespace, rstrip()
        # is the identity and exact equality was already handled above, so this
        # can only fire for a genuine trailing-whitespace strip. Trailing
        # whitespace replaced by other characters (e.g. spaces -> "\n") still
        # falls through and mismatches.
        if actual_str == sent_str.rstrip():
            return True
        # Tolerate Airtable's dateTime round-trip: ``+00:00`` (sent) vs ``.000Z``
        # (persisted) are the same instant. Compared by instant, so two different
        # times still mismatch and non-datetime scalars fall through untouched.
        return CourseCraftClient._datetime_instants_match(sent_value, actual)

    def _verify_persisted(
        self,
        table: str,
        record_id: str,
        sent_fields: Dict[str, Any],
    ) -> Dict:
        """Confirm a write actually persisted by re-reading the record.

        Performs a fresh, direct (uncached) read of ``record_id`` and raises
        ``WriteVerificationError`` if the record is absent. For plain scalar
        fields that round-trip unchanged, it also confirms the persisted value
        matches what was sent, byte for byte, so neither a fabricated response
        nor a server-side rewrite of the content can be reported as success.

        A long-text value that Airtable rewrote (Markdown canonicalization in a
        ``richText`` field) fails here, and the error names the ``richText``
        field type as the cause.

        Args:
            table: Table name the write targeted.
            record_id: Record ID returned by the write.
            sent_fields: Field map that was sent to Airtable.

        Returns:
            The freshly read record dict.

        Raises:
            WriteVerificationError: If the record cannot be re-read or a
                verifiable field does not match.
        """
        record = self.get_record(table, record_id)
        if not record:
            raise WriteVerificationError(
                f"Write to {table} reported record '{record_id}' but a fresh "
                f"read found no such record. The write did not persist."
            )

        persisted = record.get("fields", {})
        mismatches = []
        mismatched_field_names = []
        long_text_mismatch = False
        for field_name, sent_value in sent_fields.items():
            if sent_value is None:
                continue
            if not self._verifiable_field_value(sent_value):
                continue
            actual = persisted.get(field_name)
            # Tolerate --typecast number/string coercion, the multi-select
            # string->array split, the dateTime instant form, and the single
            # trailing newline Airtable appends to a richText value. Every other
            # difference is a mutation (see _persisted_value_matches).
            if not self._persisted_value_matches(sent_value, actual):
                mismatches.append(
                    self._describe_mismatch(field_name, sent_value, actual)
                )
                mismatched_field_names.append(field_name)
                if isinstance(sent_value, str) and isinstance(actual, str):
                    long_text_mismatch = True

        if mismatches:
            message = (
                f"Write to {table} record '{record_id}' did not persist as sent. "
                f"Field mismatches: {'; '.join(mismatches)}"
            )
            if long_text_mismatch:
                message = f"{message} {_RICH_TEXT_CAUSE_HINT}"
            raise WriteVerificationError(
                message, mismatched_fields=frozenset(mismatched_field_names)
            )

        return record

    def create_record(
        self,
        table: str,
        fields: Dict[str, Any]
    ) -> str:
        """
        Create a record in an Airtable table.

        After the create call returns an ID, the write is confirmed with a fresh
        uncached read before the ID is returned. If the record cannot be
        re-read, ``WriteVerificationError`` is raised so a non-persisted write
        can never be reported as success.

        Args:
            table: Table name
            fields: Dict of field names to values

        Returns:
            Created record ID

        Raises:
            ClientError: If creation fails
            WriteVerificationError: If the created record cannot be confirmed
        """
        self._ensure_mutation_allowed(table, fields=fields)
        planning_fields = self._planning_fields(table, {}, fields)
        planned_fields = plan_record_update(
            table,
            "<new record>",
            fields,
            planning_fields,
            self._field_storage_metadata(table),
        )

        # --typecast lets Airtable auto-create a brand-new singleSelect option
        # (e.g., a new "Template Deck Version" like "2026.05.a") and coerce
        # scalar values, matching update_record's behavior. Without it, Airtable
        # rejects an unknown select option and the create fails.
        args = ["records", "create", table, "--base", self.base_id, "--typecast"]

        # Add fields as arguments
        for field_name, value in planned_fields.items():
            if value is not None and value != "":
                args.append(_airtable_field_arg(field_name, value))

        response = self._run_airtable_command(args)
        record_id = self._extract_record_id(response)
        self._verify_persisted(table, record_id, planned_fields)
        return record_id

    def list_records(
        self,
        table: str,
        filter_formula: Optional[str] = None
    ) -> List[Dict]:
        """
        List ALL records from a table, following Airtable pagination.

        Airtable returns at most 100 records per page plus an ``offset`` token
        when more pages remain. This requests one page at a time and keeps
        following the returned offset until Airtable stops issuing one, so the
        full result set is returned no matter how many records match. Callers
        that want a smaller slice apply ``--limit`` to the returned list
        client-side; without a limit they receive every matching record.

        Args:
            table: Table name
            filter_formula: Optional Airtable filter formula

        Returns:
            List of record dicts (all pages accumulated)

        Raises:
            ClientError: If listing fails
        """
        records: List[Dict] = []
        offset: Optional[str] = None

        while True:
            args = [
                "records",
                "list",
                table,
                "--base",
                self.base_id,
                "--limit",
                str(AIRTABLE_PAGE_SIZE),
            ]

            if filter_formula:
                args.extend(["--formula", filter_formula])
            if offset:
                args.extend(["--offset", offset])

            response = self._run_airtable_command(args)

            # Response format: {"records": [...], "offset": "..."}
            records.extend(response.get("records", []))

            offset = response.get("offset")
            if not offset:
                break

        return records

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

    def check_slide_exists(
        self,
        clip_record_id: str,
        template_record_id: Optional[str] = None,
        clip_order: Optional[int] = None,
    ) -> Optional[str]:
        """
        Check if a slide with the same clip, template, and clip order exists.

        Duplicate identity is the exact (Clip, Template, Clip Order) triple, so
        one clip can legitimately hold several slides built from one template at
        different clip orders -- a clip with two demos needs two Demo Intro
        slides on the same Demo Intro template. ``None`` means "not provided"
        and matches records where that field is blank, which is how Content
        Slides (blank template, blank clip order) are matched.

        Airtable coerces a blank numeric cell to 0, so ``{Clip Order}=BLANK()``
        also matches ``Clip Order = 0`` and ``{Clip Order}=0`` also matches a
        blank cell. Comparing ``({Field}&'')`` against a string sidesteps that
        coercion and matches blank and non-blank values exactly.

        Note: Requires 'Clip Record ID' and 'Template Record ID' lookup fields
        in the Slides table. If not present, this check will not work correctly.

        Args:
            clip_record_id: Parent clip record ID
            template_record_id: Template record ID to match, or None for blank
            clip_order: Clip order to match, or None for blank

        Returns:
            Record ID of the exact match, None otherwise
        """
        clip_value = escape_value(clip_record_id)
        template_value = "" if template_record_id is None else escape_value(template_record_id)
        order_value = "" if clip_order is None else str(clip_order)
        filter_formula = (
            f"AND({{Clip Record ID}}='{clip_value}', "
            f"({{Template Record ID}}&'')='{template_value}', "
            f"({{Clip Order}}&'')='{order_value}')"
        )
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
        self._ensure_mutation_allowed(table, record_id=record_id)

        args = ["records", "delete", table, record_id, "--base", self.base_id, "--yes"]

        full_args = ["airtable"] + args
        try:
            result = subprocess.run(
                full_args,
                stdin=subprocess.DEVNULL,
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

    def upload_attachment(
        self,
        record_id: str,
        field_name: str,
        file_path: str,
    ) -> Dict:
        """
        Upload a local file to a record's attachment field.

        Delegates to `airtable records upload-attachment`, which owns the
        Airtable PAT and the content-upload endpoint. The CourseCraft base ID is
        passed as a runtime argument (never a shell literal), matching every
        other airtable CLI invocation in this client.

        Args:
            record_id: Existing record ID to attach to
            field_name: Attachment field ID or name (e.g., "Image")
            file_path: Path to the local file to upload

        Returns:
            Parsed JSON response from the airtable CLI

        Raises:
            ClientError: If the upload fails (missing file, size limit, API error)
        """
        args = [
            "records",
            "upload-attachment",
            record_id,
            field_name,
            file_path,
            "--base",
            self.base_id,
        ]

        full_args = ["airtable"] + args
        try:
            result = subprocess.run(
                full_args,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=AIRTABLE_CLI_COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise ClientError(
                f"airtable CLI upload-attachment timed out after {AIRTABLE_CLI_COMMAND_TIMEOUT_SECONDS}s"
            )

        if result.returncode != 0:
            raise ClientError(
                f"Failed to upload attachment to {record_id} field '{field_name}': "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        # Parse the JSON record from the airtable CLI output (skip status lines).
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("{") or line.startswith("["):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            raise ClientError(
                f"Could not parse airtable upload-attachment output: {result.stdout}"
            )

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

    def get_demos_by_clip(self, clip_record_id: str, filter_formula: Optional[str] = None) -> List[Dict]:
        """
        Get all demos belonging to a clip.

        Args:
            clip_record_id: Clip record ID
            filter_formula: Optional additional Airtable filter formula, AND-ed
                with the clip formula (mirrors the --course/--filter AND pattern
                in ``list_modules``)

        Returns:
            List of demo record dicts
        """
        formula = f"{{Clip Record ID}}='{clip_record_id}'"
        if filter_formula:
            formula = f"AND({formula},{filter_formula})"
        return self.list_records("Demos", formula)

    def get_slides_by_clip(self, clip_record_id: str, filter_formula: Optional[str] = None) -> List[Dict]:
        """
        Get all slides belonging to a clip.

        Args:
            clip_record_id: Clip record ID
            filter_formula: Optional additional Airtable filter formula, AND-ed
                with the clip formula

        Returns:
            List of slide record dicts
        """
        formula = f"{{Clip Record ID}}='{clip_record_id}'"
        if filter_formula:
            formula = f"AND({formula},{filter_formula})"
        return self.list_records("Slides", formula)

    def get_demos_by_module(self, module_record_id: str, filter_formula: Optional[str] = None) -> List[Dict]:
        """
        Get all demos for all clips in a module.

        Args:
            module_record_id: Module record ID
            filter_formula: Optional additional Airtable filter formula, AND-ed
                into every clip-level demo query

        Returns:
            List of demo record dicts
        """
        clips = self.get_clips_by_module(module_record_id)
        demos = []
        for clip in clips:
            clip_demos = self.get_demos_by_clip(clip['id'], filter_formula=filter_formula)
            demos.extend(clip_demos)
        return demos

    def get_demos_by_course(self, course_identifier: str, filter_formula: Optional[str] = None) -> List[Dict]:
        """
        Get all demos for a course.

        Args:
            course_identifier: Course slug or record ID
            filter_formula: Optional additional Airtable filter formula, AND-ed
                into every module-level demo query

        Returns:
            List of demo record dicts
        """
        course_id = self.resolve_course_id(course_identifier)
        modules = self.get_modules_by_course(course_id)
        demos = []
        for module in modules:
            module_demos = self.get_demos_by_module(module['id'], filter_formula=filter_formula)
            demos.extend(module_demos)
        return demos

    def get_slides_by_module(self, module_record_id: str, filter_formula: Optional[str] = None) -> List[Dict]:
        """
        Get all slides for all clips in a module.

        Args:
            module_record_id: Module record ID
            filter_formula: Optional additional Airtable filter formula, AND-ed
                into every clip-level slide query

        Returns:
            List of slide record dicts
        """
        clips = self.get_clips_by_module(module_record_id)
        slides = []
        for clip in clips:
            clip_slides = self.get_slides_by_clip(clip['id'], filter_formula=filter_formula)
            slides.extend(clip_slides)
        return slides

    def get_slides_by_course(self, course_identifier: str, filter_formula: Optional[str] = None) -> List[Dict]:
        """
        Get all slides for a course.

        Args:
            course_identifier: Course slug or record ID
            filter_formula: Optional additional Airtable filter formula, AND-ed
                into every module-level slide query

        Returns:
            List of slide record dicts
        """
        course_id = self.resolve_course_id(course_identifier)
        modules = self.get_modules_by_course(course_id)
        slides = []
        for module in modules:
            module_slides = self.get_slides_by_module(module['id'], filter_formula=filter_formula)
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
            message = str(e).lower()
            if any(marker in message for marker in _RECORD_NOT_FOUND_MARKERS):
                return None
            raise

    def _linked_record_id(self, value: Any) -> Optional[str]:
        """Return the first linked Airtable record ID from a scalar/list field."""
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.startswith("rec"):
                    return item
            return None
        if isinstance(value, str) and value.startswith("rec"):
            return value
        return None

    def _truthy_checkbox(self, value: Any) -> bool:
        """Airtable checkbox truthiness for API reads and CLI typecast strings."""
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return False

    def _disabled_course_error(self, course: Dict[str, Any]) -> ClientError:
        fields = course.get("fields", {}) if isinstance(course, dict) else {}
        name = fields.get("Name") or course.get("id", "")
        notes = fields.get("Disabled Notes")
        message = f"Course is disabled: {name} ({course.get('id', '')}). Changes are blocked."
        if isinstance(notes, str) and notes.strip():
            message = f"{message} Disabled Notes: {notes.strip()}"
        return ClientError(message)

    def _course_from_record_reference(self, table: str, record_id: str) -> Optional[Dict[str, Any]]:
        record = self.get_record(table, record_id)
        if not record:
            return None
        return self._course_from_record(table, record)

    def _course_from_record(self, table: str, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        fields = record.get("fields", {}) if isinstance(record, dict) else {}
        if table == "Courses":
            return record
        if table == "Modules":
            course_id = self._linked_record_id(fields.get("Course Record ID") or fields.get("Course"))
            return self.get_record("Courses", course_id) if course_id else None
        if table == "Clips":
            module_id = self._linked_record_id(fields.get("Module Record ID") or fields.get("Module"))
            return self._course_from_record_reference("Modules", module_id) if module_id else None
        if table in {"Demos", "Slides"}:
            clip_id = self._linked_record_id(fields.get("Clip Record ID") or fields.get("Clip"))
            return self._course_from_record_reference("Clips", clip_id) if clip_id else None
        if table == "Feedback":
            for linked_table, field_name in (
                ("Courses", "Course"),
                ("Modules", "Module"),
                ("Clips", "Clip"),
                ("Demos", "Demo"),
                ("Slides", "Slide"),
            ):
                linked_id = self._linked_record_id(fields.get(field_name))
                if linked_id:
                    return self._course_from_record_reference(linked_table, linked_id)
        return None

    def _course_from_create_fields(self, table: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if table == "Courses":
            return None
        if table == "Modules":
            course_id = self._linked_record_id(fields.get("Course Record ID") or fields.get("Course"))
            return self.get_record("Courses", course_id) if course_id else None
        if table == "Clips":
            module_id = self._linked_record_id(fields.get("Module Record ID") or fields.get("Module"))
            return self._course_from_record_reference("Modules", module_id) if module_id else None
        if table in {"Demos", "Slides"}:
            clip_id = self._linked_record_id(fields.get("Clip Record ID") or fields.get("Clip"))
            return self._course_from_record_reference("Clips", clip_id) if clip_id else None
        if table == "Feedback":
            pseudo = {"id": "", "fields": fields}
            return self._course_from_record("Feedback", pseudo)
        return None

    def _ensure_mutation_allowed(
        self,
        table: str,
        *,
        record_id: Optional[str] = None,
        fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Block mutations to disabled courses and records inside them."""
        if table not in _COURSE_SCOPED_TABLES:
            return

        if table == "Courses" and record_id and fields and set(fields).issubset(_COURSE_DISABLE_FIELDS):
            existing = self.get_record("Courses", record_id)
            if existing and self._truthy_checkbox(existing.get("fields", {}).get("Disabled")):
                raise self._disabled_course_error(existing)
            return

        if record_id:
            course = self._course_from_record_reference(table, record_id)
        else:
            course = self._course_from_create_fields(table, fields or {})

        if course and self._truthy_checkbox(course.get("fields", {}).get("Disabled")):
            raise self._disabled_course_error(course)

    def update_record(
        self,
        table: str,
        record_id: str,
        fields: Dict[str, Any],
    ) -> Dict:
        """
        Update a record in an Airtable table.

        After the update call returns, the write is confirmed with a fresh
        uncached read before the result is returned. If the record cannot be
        re-read, or a verifiable scalar field did not persist as sent,
        ``WriteVerificationError`` is raised so a non-persisted update can never
        be reported as success.

        Args:
            table: Table name
            record_id: Record ID to update
            fields: Dict of field names to values
        Returns:
            Updated record dict (the freshly verified read)

        Raises:
            ClientError: If update fails
            WriteVerificationError: If the update cannot be confirmed
        """
        self._ensure_mutation_allowed(table, record_id=record_id, fields=fields)
        current = self.get_record(table, record_id)
        if not current:
            raise ClientError(f"{table} record not found before update: {record_id}")
        current_fields = self._planning_fields(table, current.get("fields", {}), fields)
        planned_fields = plan_record_update(
            table,
            record_id,
            fields,
            current_fields,
            self._field_storage_metadata(table),
        )

        args = ["records", "update", table, record_id, "--base", self.base_id, "--typecast"]

        # Add fields as arguments
        for field_name, value in planned_fields.items():
            if value is not None:
                args.append(_airtable_field_arg(field_name, value))

        self._run_airtable_command(args)
        return self._verify_persisted(table, record_id, planned_fields)


# Module-level client instance - singleton pattern
_client: Optional[CourseCraftClient] = None


def get_client() -> CourseCraftClient:
    """Get or create the global CourseCraft client instance."""
    global _client
    if _client is None:
        _client = CourseCraftClient()
    return _client
