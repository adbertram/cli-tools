"""CourseCraft centralized artifact-versioning engine.

CourseCraft used to have five separate ad-hoc hash/versioning mechanisms
(Voice Source Hash, Slide Deck Hash, the walkthrough executable-cues hash, the
per-command "content changed" strip-compare, and no versioning at all on
Courses). This module plans version-bump + review-clear as ONE atomic
pre-write operation at the CLI's Airtable write chokepoint
(``CourseCraftClient.create_record`` / ``update_record`` in ``client.py``).

Single source of truth for slug identity: ``coverage-map.json`` (owned by the
course-pipeline skill, ``.agents/skills/course-pipeline/tools/data/`` in the
CourseCraft checkout). This module never mirrors that data in a second Python
table -- every slug/table/field lookup below is derived from the JSON file at
call time (cached per-process).

Paired review-clear targets (which "... Review (AI)" / human-verified field to
clear when a slug's content changes) are read from ``course-pipeline.json``'s
existing ``review_ai``/``review_target`` graph, not duplicated here either. A
``human_verified_pairs`` key on that same file (``{slug: [field, ...]}``) is
reserved for a later phase; it contributes nothing until that key exists.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .coursecraft_project import COURSES_ROOT, coursecraft_project_root
from .field_mappings import FIELD_MAPPINGS, validate_field

COVERAGE_MAP_RELATIVE_PATH = ".agents/skills/course-pipeline/tools/data/coverage-map.json"
COURSE_PIPELINE_ROUTER_RELATIVE_PATH = "course-pipeline.json"

# coverage-map.json's lowercase ``table`` values -> the Airtable table name
# used everywhere else in this CLI (client.py, field_mappings.py). Matches
# field-to-slug.json's ``_resource_table`` mapping exactly.
_RESOURCE_TABLE: Dict[str, str] = {
    "courses": "Courses",
    "modules": "Modules",
    "clips": "Clips",
    "demos": "Demos",
    "slides": "Slides",
}

VERSION_CONTROL_CLI_FIELD = "version_control"

# Slides is a lookup field (via Template Record ID), not a CLI-mapped field --
# same raw-field-name convention already used to read it in
# commands/clips.py and commands/modules.py.
SLIDE_TEMPLATE_NAME_FIELD = "Template Name"


class VersioningError(ValueError):
    """Fail-fast error for the versioning engine.

    Raised for missing/malformed coverage-map or course-pipeline data, a
    corrupt Version Control ledger, or a write that changes a slug's content
    and explicitly sets that slug's paired review field in the same call.
    """


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise VersioningError(
            f"Required CourseCraft versioning data is missing: {path}. "
            "This self-heals on the next real write once the file exists; "
            "there is no fallback path."
        )
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def coverage_map() -> Dict[str, Any]:
    """coverage-map.json's ``artifacts`` map: slug -> artifact entry."""
    path = coursecraft_project_root() / COVERAGE_MAP_RELATIVE_PATH
    data = _read_json(path)
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        raise VersioningError(f"{path} has no top-level 'artifacts' object.")
    return artifacts


@lru_cache(maxsize=1)
def _pipeline_router() -> Dict[str, Any]:
    """course-pipeline.json, parsed once per process."""
    path = coursecraft_project_root() / COURSE_PIPELINE_ROUTER_RELATIVE_PATH
    return _read_json(path)


@lru_cache(maxsize=1)
def _content_slug_index() -> Dict[Tuple[str, str], Tuple[str, ...]]:
    """(Airtable table, Airtable field) -> candidate ``airtable_content`` slugs.

    Derived from coverage-map.json's ``artifacts`` map so this reverse index
    has exactly one home; see the module docstring. Most (table, field) pairs
    resolve to exactly one slug. The Slides table's Script/Build
    Instructions/Name fields are shared by several slide types and resolve to
    more than one candidate -- see :func:`_resolve_slide_slug`.
    """
    index: Dict[Tuple[str, str], List[str]] = {}
    for slug, entry in coverage_map().items():
        if entry.get("kind") != "airtable_content":
            continue
        table_key = entry.get("table")
        table = _RESOURCE_TABLE.get(table_key)
        if table is None:
            raise VersioningError(
                f"coverage-map.json artifact {slug!r} declares unknown table "
                f"{table_key!r}."
            )
        for field in entry.get("content_fields", []):
            index.setdefault((table, field), []).append(slug)
    return {key: tuple(slugs) for key, slugs in index.items()}


@lru_cache(maxsize=1)
def _slide_type_slugs() -> Tuple[str, ...]:
    """Every Slides-table ``airtable_content`` slug that models a slide type.

    Used to resolve which slide-type slug a Slides-table write's record
    belongs to, independent of which particular field the write touched.
    This must be the FULL slide-type universe, not just the field-specific
    candidates from :func:`_content_slug_index` -- a field claimed by only
    one slug (e.g. ``Name``, unique to ``slide.module_recap``) still needs
    Template Name cross-checked against every OTHER slide type before that
    one candidate can be trusted for THIS record (see Finding 1: a single
    index candidate does not mean the field belongs to that slug for a
    record whose actual type is different).
    """
    return tuple(
        slug
        for slug, entry in coverage_map().items()
        if entry.get("kind") == "airtable_content" and entry.get("table") == "slides"
    )


def _resolve_slide_slug(
    candidates: Tuple[str, ...], persisted_fields: Dict[str, Any]
) -> Optional[str]:
    """Disambiguate a multi-candidate Slides-table slug set.

    Several slide artifacts (course_intro, module_intro, clip_intro,
    demo_intro, content) share the Slides table's Script/Build
    Instructions/Name fields, so which slug a write touched cannot be read
    off the changed field name alone. coverage-map.json's ``slide.*`` entries
    each carry a ``slide_type`` key -- the exact ``Template Name`` string that
    identifies that slide type (``slide.content``'s ``slide_type`` is
    ``None``: the fallback slug when the record matches none of the named
    types). Resolution is a dict lookup against the record's ACTUAL persisted
    ``Template Name`` value, never a hardcoded if/elif chain and never a guess
    from the candidate list alone.

    ``Template Name`` is an Airtable lookup field, so ``persisted_fields``
    holds it as a list; the first/only element is used (same convention as
    the ``Template Name`` reads in ``commands/clips.py`` and
    ``commands/modules.py``). Both sides of the match are
    ``.strip().lower()``-normalized.

    If the normalized Template Name matches exactly one candidate's
    ``slide_type``, that slug is returned. If it matches none of the
    candidates' non-``None`` ``slide_type`` values, the one candidate (if any)
    whose ``slide_type`` is ``None`` -- the documented content fallback -- is
    returned. If Template Name is missing/empty, or more than one candidate's
    ``slide_type`` matches (should never happen with correct data), the write
    is unresolvable: it is skipped (no version stamp, no review-clear), never
    guessed, since stamping the wrong slug would poison that slug's hash
    history permanently.
    """
    if len(candidates) == 1:
        return candidates[0]

    cmap = coverage_map()
    raw_template_name = persisted_fields.get(SLIDE_TEMPLATE_NAME_FIELD)
    if isinstance(raw_template_name, list):
        # A lookup field with more than one linked value has no single
        # answer for "this record's slide type" -- treat it the same as
        # missing/empty rather than silently taking element [0] (Finding 4).
        if len(raw_template_name) != 1:
            return None
        template_name = raw_template_name[0]
    else:
        template_name = raw_template_name
    normalized = str(template_name).strip().lower() if template_name else ""
    if not normalized:
        return None

    fallback_slug: Optional[str] = None
    matches: List[str] = []
    for slug in candidates:
        slide_type = cmap.get(slug, {}).get("slide_type")
        if slide_type is None:
            fallback_slug = slug
            continue
        if str(slide_type).strip().lower() == normalized:
            matches.append(slug)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None  # ambiguous data -- fail-fast, never guess
    return fallback_slug


def canonical_hash(slug: str, persisted: Any) -> str:
    """sha256 of one coverage-map slug's canonical content.

    Args:
        slug: A coverage-map.json artifact slug.
        persisted: For an ``airtable_content`` slug, the record's PERSISTED
            ``fields`` dict -- the readback from ``_verify_persisted``, never
            the value that was sent (Airtable canonicalizes long text
            server-side, so the sent bytes and the stored bytes can differ).
            For a ``file`` slug, a path to the file on disk.

    Multi-field slugs (more than one entry in ``content_fields``) hash
    ``"\\n".join(f"{field}\\x00{value}")`` with fields sorted by name, so a
    change to any one field changes the whole slug's hash.
    """
    entry = coverage_map().get(slug)
    if entry is None:
        raise VersioningError(f"Unknown coverage-map slug: {slug!r}")

    kind = entry.get("kind")
    if kind == "airtable_content":
        fields = entry.get("content_fields") or []
        if not fields:
            raise VersioningError(
                f"coverage-map.json artifact {slug!r} has no content_fields."
            )
        if len(fields) == 1:
            value = persisted.get(fields[0]) or ""
            return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
        parts = [f"{field}\x00{persisted.get(field) or ''}" for field in sorted(fields)]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    if kind == "file":
        # Path containment: a file-kind slug's path must resolve inside the
        # courses tree before it is ever read. Mirrors the equivalent check
        # in the skills repo's preflight_lib.py (_current_slug_sha), reusing
        # this repo's own courses-root constant rather than inventing a
        # second source of truth for it (Finding 7).
        try:
            resolved = Path(persisted).resolve()
            resolved.relative_to(COURSES_ROOT.resolve())
        except (OSError, ValueError):
            raise VersioningError(
                f"coverage-map.json artifact {slug!r} file path is outside "
                f"the courses root ({COURSES_ROOT}) or invalid: {persisted!r}"
            ) from None
        try:
            data = resolved.read_bytes()
        except OSError as error:
            # A real OS-level read failure (permission denied, an un-hydrated
            # Google Drive placeholder's "Operation timed out"/`fcopyfile
            # failed`, etc.) must surface as VersioningError, not a raw
            # OSError -- callers such as ``versions_sync``'s per-record walk
            # only guard against ``(ClientError, VersioningError)`` and would
            # otherwise abort the whole course walk on one bad file.
            raise VersioningError(
                f"coverage-map.json artifact {slug!r} file could not be read: "
                f"{resolved} ({error})"
            ) from None
        return hashlib.sha256(data).hexdigest()

    raise VersioningError(
        f"coverage-map.json artifact {slug!r} has kind {kind!r}, which "
        "canonical_hash does not know how to hash (expected 'airtable_content' "
        "or 'file')."
    )


@lru_cache(maxsize=1)
def _artifact_owning_reference_index() -> Dict[str, str]:
    """artifact_reference -> slug, for every non-review work-phase artifact.

    Used to resolve a review artifact's implicit target when its
    course-pipeline.json work-phase entry carries ``review_ai`` but omits an
    explicit ``review_target`` (today: module-review, powerpoint-deck-review). Such an entry shares its
    ``artifact_reference`` with exactly one content-producing artifact whose
    ``skill`` IS the slug.
    """
    index: Dict[str, str] = {}
    for phase in _pipeline_router().get("work_phases", []):
        for artifact in phase.get("artifacts", []):
            skill = artifact.get("skill")
            ref = artifact.get("artifact_reference")
            if isinstance(skill, str) and skill in coverage_map() and isinstance(ref, str):
                index[ref] = skill
    return index


def _paired_review_targets(slug: str) -> List[str]:
    """Airtable fields to clear (to ``""``) when ``slug``'s content changes.

    Two data sources, read fresh from the cached course-pipeline.json (a) and
    (b):

    (a) Every work-phase artifact whose ``review_ai`` names an Airtable field
        AND whose target is this slug contributes that field. The target is
        the artifact's explicit ``review_target`` when present, else the slug
        that shares its ``artifact_reference`` (see
        :func:`_artifact_owning_reference_index`) -- course-pipeline.json
        already carries this mapping; it is read here, never duplicated.
    (b) course-pipeline.json's ``human_verified_pairs`` map:
        ``{slug: [field, ...]}``. Every field it names is cleared to ``""``
        the same as an AI-review field; a non-text (e.g. checkbox) pair would
        need this function extended if one is ever added, which it is not
        today.

    Both sources can name a field that lives on a DIFFERENT table than
    ``slug``'s own content -- e.g. ``module-slide-build-review``'s
    ``Slide Build Review (AI)`` lives on Modules but is individually targeted
    at each ``slide.*`` slug (Slides). ``stamp_versions``'s follow-up write
    always targets the SAME record it just wrote, so a cross-table field is
    never a valid write there. This is documented, intentional V1 scope (see
    the versioning framework plan's named follow-up 1: cross-record composite
    review staleness is out of V1 scope on purpose) -- a cross-table field is
    silently excluded here, never raised as an error. Membership is checked
    against ``FIELD_MAPPINGS`` (the same table-ownership source
    ``validate_field`` uses), keyed by ``slug``'s own
    ``coverage_map()[slug]["table"]`` (mapped through ``_RESOURCE_TABLE`` to
    the Airtable table name).
    """
    router = _pipeline_router()
    owning_ref = _artifact_owning_reference_index().get(slug)

    slug_table_key = coverage_map().get(slug, {}).get("table")
    slug_table = _RESOURCE_TABLE.get(slug_table_key)
    same_table_fields = frozenset(FIELD_MAPPINGS.get(slug_table, {}).values()) if slug_table else frozenset()

    fields: List[str] = []
    for phase in router.get("work_phases", []):
        for artifact in phase.get("artifacts", []):
            review_ai = artifact.get("review_ai")
            if not isinstance(review_ai, dict):
                continue
            target = artifact.get("review_target")
            is_match = target == slug or (
                target is None and owning_ref is not None
                and artifact.get("artifact_reference") == owning_ref
            )
            if not is_match:
                continue
            field = review_ai.get("field")
            if field and field in same_table_fields and field not in fields:
                fields.append(field)
    for field in router.get("human_verified_pairs", {}).get(slug, []):
        if field in same_table_fields and field not in fields:
            fields.append(field)
    return fields


def check_write_conflict(
    table: str,
    sent_fields: Dict[str, Any],
    *,
    fetch_persisted_fields: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
) -> None:
    """Pre-write guard: reject a content+its-own-review write before it lands.

    Called from ``client.py``'s ``create_record``/``update_record`` BEFORE
    the Airtable write is issued. ``stamp_versions``'s own post-write check
    (below) catches the same conflict too late -- the corrupt content+review
    pairing has already reached Airtable by the time that check runs, and by
    then no Version Control entry gets created for the touched slug, so
    ``preflight_lib.ai_review_status()`` reads the record as clean/unsynced
    rather than stale (Finding 2). Unlike ``stamp_versions``, this makes no
    attempt to detect whether the content would actually CHANGE first --
    sending a content field and its own paired review field in one call is
    never legitimate regardless of whether the content differs from what is
    already stored, so rejecting unconditionally on ``sent_fields`` alone is
    both simpler and strictly correct.

    Conservative on the Slides table by design: at this point there is no
    readback yet (a pre-write check must add zero extra API calls), so
    Template Name is not known unless it is itself in ``sent_fields``. Every
    field-specific candidate slug is therefore treated as a possible match,
    not just the one slug Template Name would eventually resolve to. This
    can reject a combination that would, after resolution, have turned out
    to target an unrelated slide type -- a rare false-positive reject that is
    an accepted trade-off against letting a real content+review corruption
    reach Airtable.

    A field whose candidate slugs cover the FULL slide-type universe (every
    entry in :func:`_slide_type_slugs`) -- ``Script``, shared identically by
    all six slide types -- is unambiguous regardless of which type the
    record actually is: whichever type it turns out to be, that type really
    does track the field as content, and every slide type pairs it to the
    same review field. That combination keeps the original zero-extra-read
    behavior: reject immediately, never call ``fetch_persisted_fields``.

    A field whose candidates are a strict SUBSET of the slide-type universe
    -- e.g. ``Name`` (``slide.module_recap`` only) or ``Build Instructions``
    (``slide.demo_intro`` / ``slide.content`` / ``slide.module_recap``) --
    could belong to a slide type this record isn't. A write that sets such a
    field alongside one of its candidate slugs' paired review field looks
    like a real conflict from the field names alone even when the record's
    actual type doesn't track that field as content at all -- e.g.
    ``commands/slides.py`` building ``--name`` + ``--script-human-verified``
    to rename a Course Intro / Module Intro / Clip Intro slide's title, which
    touches no tracked content on those types, or ``--build-instructions`` +
    ``--script-human-verified`` on the same non-demo/content/module_recap
    types. This is the general form of the same ambiguity: derived
    structurally from ``_content_slug_index()`` vs. ``_slide_type_slugs()``,
    never hardcoded by field name. Resolution is spent at most once total
    per call, cached across every candidate slug and field examined: when
    ``fetch_persisted_fields`` is supplied (``update_record`` passes a
    callback that re-reads the record; ``create_record`` passes none, since
    there is no persisted record yet to read), it resolves the record's real
    slide-type slug the same way ``stamp_versions`` does, and the reject only
    fires if that real slug matches the candidate under test. Without a
    resolver (``create_record``), the check stays conservative and rejects,
    same as it always has.
    """
    if table not in _RESOURCE_TABLE.values():
        return

    candidate_slugs: set = set()
    for field_name in sent_fields:
        candidates = _content_slug_index().get((table, field_name))
        if candidates:
            candidate_slugs.update(candidates)

    slide_universe_size = len(_slide_type_slugs()) if table == "Slides" else 0
    resolution_attempted = False
    resolved_real_slug: Optional[str] = None

    for slug in sorted(candidate_slugs):
        for review_field in _paired_review_targets(slug):
            if review_field not in sent_fields:
                continue
            if sent_fields[review_field] in (None, "", False):
                # Clearing stale review evidence is a required consequence of
                # the same atomic owner write; only a new affirmative/review
                # value conflicts with changing its reviewed content.
                continue

            content_fields = coverage_map().get(slug, {}).get("content_fields", ())
            needs_resolution = table == "Slides" and any(
                field in sent_fields
                and len(_content_slug_index().get((table, field), ())) < slide_universe_size
                for field in content_fields
            )
            if needs_resolution and fetch_persisted_fields is not None:
                if not resolution_attempted:
                    resolution_attempted = True
                    fresh_fields = fetch_persisted_fields()
                    resolved_real_slug = (
                        _resolve_slide_slug(_slide_type_slugs(), fresh_fields)
                        if fresh_fields is not None
                        else None
                    )
                if resolved_real_slug != slug:
                    # The record's real slide type either isn't this
                    # candidate, or is itself unresolvable -- never guess,
                    # and never reject a combination that resolution
                    # disproved.
                    continue
            # else: either unambiguous (needs_resolution is False, e.g.
            # Script) or ambiguous with no resolver available (create_record)
            # -- both fall through and reject, the latter staying
            # conservative exactly as before.

            raise VersioningError(
                f"{table}: cannot set {slug!r}'s content field(s) and its "
                f"paired review field {review_field!r} in the same write. "
                "Clear stale review evidence in this write, then establish a "
                "new review only after the content persists."
            )


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode_version_control(
    raw: Any, table: str, record_id: str, version_field: str, context: str
) -> Dict[str, Any]:
    """Parse one Version Control JSON blob, or raise VersioningError.

    One home for fail-closed Version Control decoding before an owner write.
    """
    suffix = f" {context}" if context else ""
    try:
        decoded = json.loads(raw) if raw else {}
    except json.JSONDecodeError as error:
        raise VersioningError(
            f"{table} record {record_id!r} field {version_field!r} is not "
            f"valid JSON{suffix}: {error}"
        ) from None
    if not isinstance(decoded, dict):
        raise VersioningError(
            f"{table} record {record_id!r} field {version_field!r} must "
            f"decode to a JSON object{suffix}, got {type(decoded).__name__}."
        )
    return decoded



_IDENTITY_STORAGE_TYPES = frozenset(
    {
        "singleLineText",
        "email",
        "url",
        "phoneNumber",
        "date",
        "dateTime",
        "singleSelect",
        "number",
        "currency",
        "percent",
        "duration",
        "rating",
    }
)


def _canonicalize_storage_value(field: str, value: Any, metadata: Dict[str, Any]) -> Any:
    """Predict Airtable's persisted value from exact field-type metadata."""
    field_type = metadata.get("type")
    if not isinstance(field_type, str) or not field_type:
        raise VersioningError(
            f"Canonicalization metadata for field {field!r} has no exact type."
        )
    if value is None:
        return None
    if field_type == "multilineText":
        # Airtable can preserve a submitted trailing newline on multilineText
        # owner fields (confirmed live for Courses."Carry-Forward Plan").
        # Predicting rstrip() here stamps a hash for bytes that were never
        # written, poisoning Version Control in the same otherwise-atomic
        # record PATCH. Hash the exact submitted value; post-write verification
        # remains responsible for rejecting an actual storage mismatch.
        return value
    if field_type == "richText":
        if not isinstance(value, str) or not value or value.endswith("\n"):
            return value
        return value + "\n"
    if field_type == "checkbox":
        return True if bool(value) else None
    if field_type == "multipleSelects":
        if isinstance(value, str):
            return sorted(part.strip() for part in value.split(",") if part.strip())
        if isinstance(value, list):
            return sorted(value, key=str)
    if field_type in {"multipleRecordLinks", "multipleAttachments"}:
        if isinstance(value, list):
            return sorted(value, key=lambda item: json.dumps(item, sort_keys=True))
    if field_type in _IDENTITY_STORAGE_TYPES:
        return value
    raise VersioningError(
        f"Field {field!r} uses unsupported Airtable storage type {field_type!r}; "
        "add an exact canonicalization rule before writing tracked content."
    )


def _tracked_slugs_for_update(
    table: str, proposed_fields: Dict[str, Any], predicted_fields: Dict[str, Any]
) -> Tuple[str, ...]:
    """Resolve the exact artifact slugs touched by one proposed owner write."""
    touched: set[str] = set()
    for field_name in proposed_fields:
        candidates = _content_slug_index().get((table, field_name))
        if not candidates:
            continue
        if table == "Slides":
            resolved = _resolve_slide_slug(_slide_type_slugs(), predicted_fields)
            if resolved is None:
                raise VersioningError(
                    f"{table}: cannot resolve the slide artifact for tracked field "
                    f"{field_name!r}; Template Name must identify exactly one slide type."
                )
            if field_name in coverage_map().get(resolved, {}).get("content_fields", ()):
                touched.add(resolved)
        elif len(candidates) == 1:
            touched.add(candidates[0])
        else:
            raise VersioningError(
                f"{table}: tracked field {field_name!r} resolves to multiple artifacts: "
                f"{', '.join(candidates)}."
            )
    return tuple(sorted(touched))


def _same_record_lifecycle_invalidation(
    table: str,
    changed_slugs: List[str],
    current_fields: Dict[str, Any],
) -> Dict[str, Any]:
    """Return contract-owned external-review invalidation consequences.

    Only review subjects stored on the same owner record can be merged into
    this PATCH. Cross-record dependencies (notably Clip recordings reviewed as
    one Module manifest) are invalidated by their owning registration workflow.
    """
    lifecycle = _pipeline_router().get("artifact_lifecycle")
    if not isinstance(lifecycle, dict):
        raise VersioningError("course-pipeline.json has no artifact_lifecycle object.")
    instances = lifecycle.get("instances")
    if not isinstance(instances, dict):
        raise VersioningError(
            "course-pipeline.json artifact_lifecycle has no instances object."
        )

    consequences: Dict[str, Any] = {}
    for instance_name, instance in instances.items():
        if not isinstance(instance, dict) or instance.get("table") != table:
            continue
        subject = instance.get("review_subject")
        if not isinstance(subject, dict) or subject.get("slug") not in changed_slugs:
            continue
        if subject.get("version_owner") != instance.get("owner"):
            continue
        state_field = instance.get("state_field")
        revision_field = instance.get("submitted_revision_field")
        if not isinstance(state_field, str) or not isinstance(revision_field, str):
            raise VersioningError(
                f"Lifecycle instance {instance_name!r} has invalid owner fields."
            )
        state = current_fields.get(state_field)
        if state in {"Submitted", "Approved"}:
            consequences[state_field] = "Not Submitted"
            consequences[revision_field] = ""
        elif state in {"Not Submitted", "Changes Requested", None}:
            continue
        else:
            raise VersioningError(
                f"Lifecycle instance {instance_name!r} has invalid current state "
                f"{state!r}; refusing tracked-content write."
            )
    return consequences


def plan_record_update(
    table: str,
    record_id: str,
    proposed_fields: Dict[str, Any],
    current_fields: Dict[str, Any],
    field_metadata: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge content, versions, and review invalidation into one owner PATCH.

    The caller supplies a fresh owner-record read plus exact Airtable field
    metadata. This function performs no writes. Identical resubmissions remain
    no-ops for Version Control and review consequences.
    """
    if table not in _RESOURCE_TABLE.values():
        return dict(proposed_fields)

    check_write_conflict(
        table,
        proposed_fields,
        fetch_persisted_fields=lambda: current_fields,
    )

    predicted_fields = dict(current_fields)
    tracked_field_names = {
        field_name
        for field_name in proposed_fields
        if _content_slug_index().get((table, field_name))
    }
    for field_name in tracked_field_names:
        metadata = field_metadata.get(field_name)
        if not isinstance(metadata, dict):
            raise VersioningError(
                f"Missing canonicalization metadata for {table}.{field_name}."
            )
        predicted_fields[field_name] = _canonicalize_storage_value(
            field_name, proposed_fields[field_name], metadata
        )

    touched_slugs = _tracked_slugs_for_update(
        table, proposed_fields, predicted_fields
    )
    changed_slugs = []
    for slug in touched_slugs:
        content_fields = coverage_map()[slug].get("content_fields") or []
        if any(
            predicted_fields.get(field) != current_fields.get(field)
            for field in content_fields
        ):
            changed_slugs.append(slug)

    if not changed_slugs:
        return dict(proposed_fields)

    version_field = validate_field(VERSION_CONTROL_CLI_FIELD, table)
    existing_vc = _decode_version_control(
        current_fields.get(version_field) or "{}",
        table,
        record_id,
        version_field,
        "before owner write",
    )
    merged_vc = dict(existing_vc)
    planned = dict(proposed_fields)
    stamped_at = now_iso()
    for slug in changed_slugs:
        current_entry = existing_vc.get(slug)
        current_v = current_entry.get("v", 0) if isinstance(current_entry, dict) else 0
        merged_vc[slug] = {
            "v": current_v + 1,
            "sha256": canonical_hash(slug, predicted_fields),
            "at": stamped_at,
        }
        for review_field in _paired_review_targets(slug):
            planned[review_field] = ""

    planned.update(
        _same_record_lifecycle_invalidation(table, changed_slugs, current_fields)
    )

    planned[version_field] = json.dumps(merged_vc, sort_keys=True)
    return planned
