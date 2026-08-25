"""Contracts for the LegoScout orchestrator."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path

from ..ledger import minifig_analysis
from ..sources import registry


SOURCE_ARTIFACT_FIELDS = (
    "source", "checked", "blocked", "blocker", "candidate_records",
    "unavailable_updates", "unchanged_duplicate_keys", "learning_notes",
    "actions_requiring_approval", "evidence_summary", "completed_at",
)
BATCH_SIZE = 25
SYNTHESIS_VALIDATION_TIMESTAMP = "2000-01-01T00:00:00Z"


class AppraisalBatchKeyError(ValueError):
    """A source batch and its appraisal results have different keys."""


def _require_list(value, label: str) -> list:
    if not isinstance(value, list):
        raise AppraisalBatchKeyError(
            "%s must be an array, got %s" % (label, type(value).__name__))
    return value


def validate_appraisal_result(record: dict, label: str = "appraisal result") -> None:
    """Require the one model verdict shape synthesis reads.

    The appraiser used three incompatible shapes in one run. Some rows omitted
    the score. Others put it at the top level, where build_deal_record silently
    dropped it. Synthesis only reads observations.model_score and
    observations.model_rationale, so this gate validates that exact shape.

    `listing_category` is checked here too, even though the scorer already
    enforces its enum, because a missing/invalid value here means the
    classifier's hand-off itself is broken -- catching it at this gate names
    that defect directly, rather than letting it surface three call-frames
    downstream as an opaque score_record error over a phantom `"unknown"`
    sentinel `build_record._typed_default` fills in for the absent field. It
    is also load-bearing for `synthesis_coverage`'s comps `expected_category`
    cross-check, which reads this same field and silently exempts a missing
    value the same way it exempts a legitimately `blocked` comps result --
    those must not be the same failure mode.
    """
    if not isinstance(record, dict):
        raise AppraisalBatchKeyError(
            "%s must be an object, got %s" % (label, type(record).__name__))
    misplaced = [name for name in ("model_score", "model_rationale")
                 if name in record]
    if misplaced:
        raise AppraisalBatchKeyError(
            "%s has misplaced top-level %s; put the model verdict under "
            "observations" % (label, ", ".join(misplaced)))
    category = record.get("listing_category")
    if category not in ("bulk", "set", "minifigure", "excluded"):
        raise AppraisalBatchKeyError(
            "%s listing_category must be 'bulk', 'set', 'minifigure', or "
            "'excluded', got %r" % (label, category))
    observations = record.get("observations")
    if not isinstance(observations, dict):
        raise AppraisalBatchKeyError(
            "%s observations must be an object, got %s"
            % (label, type(observations).__name__))
    score = observations.get("model_score")
    if (isinstance(score, bool) or not isinstance(score, (int, float))
            or not math.isfinite(score) or not 0 <= score <= 100):
        raise AppraisalBatchKeyError(
            "%s observations.model_score must be a finite number from 0 to 100, "
            "got %r" % (label, score))
    rationale = observations.get("model_rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise AppraisalBatchKeyError(
            "%s observations.model_rationale must be a non-empty string"
            % label)


def validate_comps_result(
    record: dict, label: str = "comps result", expected_category: str | None = None
) -> None:
    """Require the shape `build_record._apply_comps` reads.

    BULK: `bricklink` and `ebay` must both be PRESENT keys, even when their
    value is null -- a bulk candidate has no bricklink lookup at all (`None`),
    and an eBay auth lapse still reports `{"available": false, "reason": ...}`,
    never an absent `ebay` key.

    SET: `sets` must be a PRESENT, non-empty array -- `legoscout pricing comps`
    prices every detected set number as one entry each, always as an array
    (even a single-set listing is a one-entry array), and every entry must
    itself carry both `bricklink` and `ebay` keys for the same reason bulk
    does. An absent or malformed key here is indistinguishable from "the
    appraiser never looked at this candidate/set", which is the failure this
    gate exists to catch.

    BLOCKED: a `set` candidate the classifier could never identify (text and
    vision both exhausted, `set_numbers` omitted per its own hand-off contract)
    has no set to call `legoscout pricing comps` for -- that is not the same
    defect as "the appraiser forgot comps for an identified set", which
    `_apply_comps` still raises on. `blocked: true` plus a non-empty `blocker`
    skips the mode/sets shape check entirely; `_apply_comps` reads it as a
    real, scoreable "stays unpriced" outcome instead of a build-time error.

    `expected_category`, when supplied, cross-checks `mode` against the
    candidate's OWN `listing_category` (from the appraisal). `_apply_comps`
    trusts `listing_category`, not `mode`, to decide how to read a comps
    result -- a bulk-shaped comps result hand to a SET candidate (or the
    reverse) previously passed this gate cleanly and then silently no-opped
    in `_apply_comps` instead of raising, writing a materially wrong
    `ebay_avg_sold_price` on a SET record with `profit_incomplete` left
    unset. A `blocked` record has no `mode` to mismatch and is exempt.
    """
    if not isinstance(record, dict):
        raise AppraisalBatchKeyError(
            "%s must be an object, got %s" % (label, type(record).__name__))
    if record.get("blocked") is True:
        blocker = record.get("blocker")
        if not isinstance(blocker, str) or not blocker.strip():
            raise AppraisalBatchKeyError(
                "%s is blocked but has no non-empty blocker" % label)
        return
    mode = record.get("mode")
    if expected_category is not None and mode != expected_category:
        raise AppraisalBatchKeyError(
            "%s has mode %r but the candidate's listing_category is %r -- "
            "a comps result shaped for the wrong category silently drops or "
            "corrupts pricing instead of raising; the appraiser must call "
            "`legoscout pricing comps` in the mode listing_category names"
            % (label, mode, expected_category))
    if mode == "bulk":
        missing = [name for name in ("bricklink", "ebay") if name not in record]
        if missing:
            raise AppraisalBatchKeyError(
                "%s is missing %s -- a bulk comps result always carries both "
                "keys, even when one is null (bulk has no bricklink; an eBay "
                "auth lapse still reports ebay: {\"available\": false, ...})"
                % (label, ", ".join(missing)))
        return

    if mode == "set":
        sets = record.get("sets")
        if not isinstance(sets, list) or not sets:
            raise AppraisalBatchKeyError(
                "%s mode is 'set' but 'sets' is %r -- it must be a non-empty "
                "array, one entry per detected set number, even for a single "
                "set" % (label, sets))
        for index, entry in enumerate(sets):
            if not isinstance(entry, dict):
                raise AppraisalBatchKeyError(
                    "%s sets[%d] must be an object, got %s"
                    % (label, index, type(entry).__name__))
            missing = [name for name in ("set_no", "bricklink", "ebay") if name not in entry]
            if missing:
                raise AppraisalBatchKeyError(
                    "%s sets[%d] is missing %s -- every set entry always "
                    "carries all three keys, even when bricklink/ebay is null"
                    % (label, index, ", ".join(missing)))
        set_no_duplicates = _duplicates([entry.get("set_no") for entry in sets
                                         if isinstance(entry, dict)])
        if set_no_duplicates:
            raise AppraisalBatchKeyError(
                "%s has duplicate set_no in sets[]: %s -- _apply_comps divides "
                "landed cost by len(sets) but sums each entry's full resale "
                "comp, so a repeated set_no double-counts that set's resale "
                "value against a single fractional cost share"
                % (label, ", ".join(set_no_duplicates)))
        return
    raise AppraisalBatchKeyError(
        "%s has mode %r -- must be 'set', 'bulk', or a blocked "
        "record" % (label, mode))


def validate_identification_result(
    record: dict,
    label: str = "identification result",
) -> None:
    if not isinstance(record, dict):
        raise AppraisalBatchKeyError(
            f"{label} must be an object, got {type(record).__name__}")
    key = record.get("listing_key")
    if not isinstance(key, str) or not key:
        raise AppraisalBatchKeyError(f"{label} has no non-empty listing_key")
    if record.get("blocked") is True:
        blocker = record.get("blocker")
        if not isinstance(blocker, str) or not blocker.strip():
            raise AppraisalBatchKeyError(
                f"{label} is blocked but has no non-empty blocker")
        if record.get("minifig_analysis") is not None:
            raise AppraisalBatchKeyError(
                f"{label} is blocked but carries minifig_analysis")
        return
    analysis = record.get("minifig_analysis")
    if not isinstance(analysis, list) or not analysis:
        raise AppraisalBatchKeyError(
            f"{label} minifig_analysis must be a non-empty array")
    try:
        normalized = [minifig_analysis.normalize_entry(entry)
                      for entry in analysis]
    except minifig_analysis.Unreadable as exc:
        raise AppraisalBatchKeyError(f"{label} minifig_analysis: {exc}") from exc
    errors = [
        f"entry {index}: {error}"
        for index, entry in enumerate(normalized)
        for error in minifig_analysis.entry_errors(entry)
    ] + minifig_analysis.batch_errors(normalized)
    if errors:
        raise AppraisalBatchKeyError(
            f"{label} minifig_analysis invalid: {'; '.join(errors)}")
    expected = {
        "figure_count": minifig_analysis.figure_count(normalized),
        "figure_count_source": "detection",
        "identified_count": minifig_analysis.identified_count(normalized),
        "unknown_count": minifig_analysis.unknown_count(normalized),
        "priced_subtotal": minifig_analysis.round_cents(
            minifig_analysis.priced_subtotal(normalized)),
        "sold_count": minifig_analysis.sold_count(normalized),
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise AppraisalBatchKeyError(
                f"{label} {field}={record.get(field)!r} does not equal "
                f"canonical {value!r}")
    complete = expected["unknown_count"] == 0 and all(
        entry.get("unit_value") is not None and not entry.get("errors")
        for entry in normalized)
    if record.get("pricing_complete") is not complete:
        raise AppraisalBatchKeyError(
            f"{label} pricing_complete does not match canonical completeness")


def validate_identification_batch(
    source_candidates: list[dict],
    appraisal_results: list[dict],
    identification_results: list[dict],
) -> dict[str, dict]:
    _require_list(source_candidates, "source candidates")
    _require_list(appraisal_results, "appraisal results")
    _require_list(identification_results, "identification results")
    candidate_keys = _listing_keys(source_candidates, "source candidate")
    appraisal_keys = _listing_keys(appraisal_results, "appraisal result")
    if set(candidate_keys) != set(appraisal_keys):
        raise AppraisalBatchKeyError(
            "appraisal keys must be validated before identification coverage")
    appraisals = {row["listing_key"]: row for row in appraisal_results}
    expected = {
        key for key in candidate_keys
        if appraisals[key].get("listing_category") == "minifigure"
    }
    keys = _listing_keys(identification_results, "identification result")
    duplicates = _duplicates(keys)
    missing = sorted(expected - set(keys))
    extra = sorted(set(keys) - expected)
    problems = []
    if duplicates:
        problems.append(
            "duplicate identification result keys: " + ", ".join(duplicates))
    if missing:
        problems.append("missing identification results: " + ", ".join(missing))
    if extra:
        problems.append("extra identification results: " + ", ".join(extra))
    if problems:
        raise AppraisalBatchKeyError(
            "identification batch key mismatch: " + "; ".join(problems))
    return {row["listing_key"]: row for row in identification_results}


def validate_comps_batch(
    source_candidates: list[dict],
    comps_results: list[dict],
    appraisal_results: list[dict] | None = None,
) -> dict[str, dict]:
    """Return comps results by key after the same exact-key check as appraisals.

    Checks coverage ONLY (duplicate/missing/extra keys) -- a genuine
    batch-wide completeness defect, since it means the appraiser never even
    acknowledged a listing_key. Per-record shape (`validate_comps_result`) is
    deliberately NOT checked here: one candidate's malformed comps entry is a
    that-candidate's-record defect, not a whole-batch one, so
    `synthesis_coverage` validates shape per-candidate inside its own
    try/except build loop instead, surfacing it as one `build_errors` entry
    rather than failing every other candidate in the same batch.
    """
    _require_list(source_candidates, "source candidates")
    _require_list(comps_results, "comps results")
    candidate_keys = _listing_keys(source_candidates, "source candidate")
    comps_keys = _listing_keys(comps_results, "comps result")

    candidate_duplicates = _duplicates(candidate_keys)
    comps_duplicates = _duplicates(comps_keys)
    candidate_set = set(candidate_keys)
    if appraisal_results is not None:
        _require_list(appraisal_results, "appraisal results")
        appraisals = {row["listing_key"]: row for row in appraisal_results}
        candidate_set = {
            key for key in candidate_keys
            if appraisals[key].get("listing_category") != "minifigure"
        }
    comps_set = set(comps_keys)
    missing = sorted(candidate_set - comps_set)
    extra = sorted(comps_set - candidate_set)

    problems = []
    if candidate_duplicates:
        problems.append("duplicate source candidate keys: %s" %
                        ", ".join(candidate_duplicates))
    if comps_duplicates:
        problems.append("duplicate comps result keys: %s" %
                        ", ".join(comps_duplicates))
    if missing:
        problems.append("missing comps results: %s" % ", ".join(missing))
    if extra:
        problems.append("extra comps results: %s" % ", ".join(extra))
    if problems:
        raise AppraisalBatchKeyError(
            "comps batch key mismatch: " + "; ".join(problems))

    return {result["listing_key"]: result for result in comps_results}


def _listing_keys(records: list[dict], label: str) -> list[str]:
    keys = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise AppraisalBatchKeyError(
                "%s %d is not an object" % (label, index))
        key = record.get("listing_key")
        if not isinstance(key, str) or not key:
            raise AppraisalBatchKeyError(
                "%s %d has no non-empty listing_key" % (label, index))
        keys.append(key)
    return keys


def _duplicates(keys: list[str]) -> list[str]:
    return sorted(key for key, count in Counter(keys).items() if count > 1)


def validate_appraisal_batch(
    source_candidates: list[dict],
    appraisal_results: list[dict],
) -> dict[str, dict]:
    """Return appraisal results by key after an exact batch-key check."""
    _require_list(source_candidates, "source candidates")
    _require_list(appraisal_results, "appraisal results")
    candidate_keys = _listing_keys(source_candidates, "source candidate")
    appraisal_keys = _listing_keys(appraisal_results, "appraisal result")
    for index, result in enumerate(appraisal_results):
        validate_appraisal_result(result, "appraisal result %d" % index)

    candidate_duplicates = _duplicates(candidate_keys)
    appraisal_duplicates = _duplicates(appraisal_keys)
    candidate_set = set(candidate_keys)
    appraisal_set = set(appraisal_keys)
    missing = sorted(candidate_set - appraisal_set)
    extra = sorted(appraisal_set - candidate_set)

    problems = []
    if candidate_duplicates:
        problems.append("duplicate source candidate keys: %s" %
                        ", ".join(candidate_duplicates))
    if appraisal_duplicates:
        problems.append("duplicate appraisal result keys: %s" %
                        ", ".join(appraisal_duplicates))
    if missing:
        problems.append("missing appraisal results: %s" % ", ".join(missing))
    if extra:
        problems.append("extra appraisal results: %s" % ", ".join(extra))
    if problems:
        raise AppraisalBatchKeyError(
            "appraisal batch key mismatch: " + "; ".join(problems))

    return {result["listing_key"]: result for result in appraisal_results}


def appraisal_coverage(
    source_candidates: list[dict], appraisal_results: list[dict]
) -> dict:
    """Return a deterministic key-coverage report for one exact batch."""
    try:
        by_key = validate_appraisal_batch(source_candidates, appraisal_results)
    except AppraisalBatchKeyError as exc:
        return {
            "complete": False,
            "candidate_count": len(source_candidates) if isinstance(source_candidates, list) else None,
            "appraisal_count": len(appraisal_results) if isinstance(appraisal_results, list) else None,
            "listing_keys": [],
            "error": str(exc),
        }
    return {
        "complete": True,
        "candidate_count": len(source_candidates),
        "appraisal_count": len(appraisal_results),
        "listing_keys": sorted(by_key),
        "error": None,
    }


def _is_pickup_radius_rejection(exc: Exception) -> bool:
    """The one error class where `status: rejected` is the sanctioned answer.

    `build_deal_record` raises a ValueError wrapping `validate.check`'s errors
    when the dry-build passes `status: active`; the pickup gate's sentence is
    stable prose from `legoscout_cli.ledger.validate`, so matching it here is
    matching the validator's own contract, not a guessed message shape.
    """
    return isinstance(exc, ValueError) and "outside the pickup radius" in str(exc)


def _is_classifier_exclusion(exc: Exception) -> bool:
    """The second error class where `status: rejected` is the sanctioned answer.

    `build_deal_record` raises `classified as excluded: ...` when a candidate
    the classifier tagged `excluded` (book, hardware, non-brick item) is dry-
    built as `active`. Retrying it as `rejected` is the whole point of the
    exclusion path -- the reason lands in `notes`, and the record is a visible
    audit row, never a deal.
    """
    return isinstance(exc, ValueError) and "classified as excluded" in str(exc)


def synthesis_coverage(
    source_candidates: list[dict],
    appraisal_results: list[dict],
    comps_results: list[dict] | None = None,
    fee_rate: float | None = None,
    identification_results: list[dict] | None = None,
) -> dict:
    """Prove exact keys and build every candidate/appraisal(/comps) pair.

    `comps_results` is optional: a batch with none proves what it always
    proved -- every BULK candidate builds, since `_apply_comps` only requires
    comps for a SET candidate. Passing comps additionally proves every SET
    candidate has a matching, well-shaped comps result; a set candidate with no
    comps in hand surfaces as a per-candidate `build_errors` entry naming
    exactly that, the same way any other malformed appraisal does.

    The fixed timestamp makes the proof deterministic. An empty favorite set
    prevents this read-only gate from opening the ledger's seller access layer.
    Favorite status changes a score bonus, not record validity. `fee_rate` is
    optional for the same reason `build_deal_record` makes it optional: this
    gate proves the record BUILDS, not what its final price is.
    """
    report = appraisal_coverage(source_candidates, appraisal_results)
    report.update(buildable_count=None, build_errors=[])
    if not report["complete"]:
        return report

    appraisals = {row["listing_key"]: row for row in appraisal_results}
    try:
        identification_by_key = validate_identification_batch(
            source_candidates,
            appraisal_results,
            identification_results if identification_results is not None else [],
        )
    except AppraisalBatchKeyError as exc:
        report["complete"] = False
        report["error"] = str(exc)
        return report
    report["identification_count"] = len(identification_by_key)

    comps_by_key = None
    if comps_results is not None:
        try:
            comps_by_key = validate_comps_batch(
                source_candidates, comps_results, appraisal_results)
        except AppraisalBatchKeyError as exc:
            report["complete"] = False
            report["error"] = str(exc)
            return report

    from ..ledger import build_record

    built = 0
    gate_rejected = 0
    errors = []
    for candidate in source_candidates:
        key = candidate["listing_key"]
        comps = comps_by_key.get(key) if comps_by_key is not None else None
        identification = identification_by_key.get(key)

        def _build(status: str):
            return build_record.build_deal_record(
                candidate,
                appraisals[key],
                first_seen_at=SYNTHESIS_VALIDATION_TIMESTAMP,
                last_seen_at=SYNTHESIS_VALIDATION_TIMESTAMP,
                favorite_sellers=set(),
                comps=comps,
                identification=identification,
                fee_rate=fee_rate,
                status=status,
            )

        try:
            if identification is not None:
                validate_identification_result(
                    identification, "identification result for %r" % key)
            if comps is not None:
                validate_comps_result(
                    comps, "comps result for %r" % key,
                    expected_category=appraisals[key].get("listing_category"))
            _build("active")
        except Exception as first_exc:  # noqa: BLE001 -- artifact defect, reported by key
            # The pickup-radius gate and the classifier-exclusion gate are the
            # two error classes where 'rejected' is the sanctioned answer, not
            # a defect: `legoscout-pricing`'s `<fulfillment>` rule says an
            # out-of-radius pickup-only listing is recorded with
            # `status: rejected` and the reason in notes, and the classifier's
            # exclusion gate says the same for a book/hardware/non-brick item
            # -- which is exactly how the real synthesis writes both. The
            # dry-build proves the pair still assembles into a valid record
            # under that status.
            if _is_pickup_radius_rejection(first_exc) or _is_classifier_exclusion(first_exc):
                try:
                    _build("rejected")
                except Exception as retry_exc:  # noqa: BLE001 -- reported by key
                    errors.append({
                        "listing_key": key,
                        "error": "%s: %s" % (type(retry_exc).__name__, retry_exc),
                    })
                else:
                    gate_rejected += 1
                    built += 1
            else:
                errors.append({
                    "listing_key": key,
                    "error": "%s: %s" % (type(first_exc).__name__, first_exc),
                })
        else:
            built += 1
    report["buildable_count"] = built
    report["gate_rejected_count"] = gate_rejected
    report["build_errors"] = errors
    if errors:
        report["complete"] = False
        report["error"] = "%d of %d exact-key pairs failed full record build" % (
            len(errors), len(source_candidates))
    return report


def _read_json(path: Path):
    if not path.is_file():
        raise ValueError("artifact is missing")
    if path.stat().st_size == 0:
        raise ValueError("artifact is empty")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("artifact is not valid JSON: %s" % exc) from None


def _batch_number(path: Path, source: str, kind: str = "appraisal") -> int | None:
    prefix = "%s.%s-" % (source, kind)
    if not path.name.startswith(prefix) or not path.name.endswith(".json"):
        return None
    number = path.name[len(prefix):-5]
    return int(number) if number.isdigit() and int(number) > 0 else None


def build_run_manifest(run_dir: str, active_sources: list[str] | None = None) -> dict:
    """Describe exact active-source and appraisal coverage for one run.

    The active source registry is the run plan. Watermark rows can outlive a
    source, so they cannot decide coverage. The output has no clock value and
    sorts every source and key. The same files produce the same manifest.
    """
    root = Path(run_dir).expanduser().resolve()
    planned = sorted(set(active_sources if active_sources is not None
                         else registry.active_namespaces()))
    all_identification_paths = sorted(root.glob("*.identify-*.json"))
    orphan_identification_artifacts = [
        str(path) for path in all_identification_paths
        if not any(path.name.startswith(source + ".identify-")
                   for source in planned)
    ]
    sources = []
    for source in planned:
        source_path = root / (source + ".json")
        problems = []
        candidates = []
        source_status = "invalid"
        try:
            envelope = _read_json(source_path)
            if not isinstance(envelope, dict):
                raise ValueError(
                    "source artifact root must be an object, got %s"
                    % type(envelope).__name__)
            missing_fields = [field for field in SOURCE_ARTIFACT_FIELDS
                              if field not in envelope]
            if missing_fields:
                problems.append("source artifact lacks: %s"
                                % ", ".join(missing_fields))
            raw_candidates = envelope.get("candidate_records")
            if not isinstance(raw_candidates, list):
                problems.append(
                    "candidate_records must be an array, got %s"
                    % type(raw_candidates).__name__)
            else:
                candidates = raw_candidates
            checked = envelope.get("checked")
            blocked = envelope.get("blocked")
            if not isinstance(checked, bool) or not isinstance(blocked, bool):
                problems.append("checked and blocked must be booleans")
            elif checked and blocked:
                problems.append("checked and blocked cannot both be true")
            elif blocked:
                source_status = "blocked"
            elif checked:
                source_status = "checked"
            else:
                problems.append("source is neither checked nor blocked")
        except ValueError as exc:
            problems.append(str(exc))
            source_status = "no_artifact" if not source_path.is_file() else "invalid"

        batch_files = {}
        for path in sorted(root.glob("%s.appraisal-*.json" % source)):
            number = _batch_number(path, source, "appraisal")
            if number is None:
                problems.append("invalid appraisal artifact name: %s" % path.name)
            elif number in batch_files:
                problems.append("duplicate appraisal batch number: %d" % number)
            else:
                batch_files[number] = path

        # Comps batches are OPTIONAL at the manifest level: a batch with none
        # still proves every BULK candidate builds (`_apply_comps` only
        # requires comps for a SET candidate). This is not a silent gap for
        # sets -- a SET candidate with no matching comps result surfaces as a
        # per-candidate `build_errors` entry inside `synthesis_coverage`,
        # exactly like any other malformed appraisal. A comps file that IS
        # present is fully validated (key coverage, shape) the same as an
        # appraisal file.
        comps_files = {}
        for path in sorted(root.glob("%s.comps-*.json" % source)):
            number = _batch_number(path, source, "comps")
            if number is None:
                problems.append("invalid comps artifact name: %s" % path.name)
            elif number in comps_files:
                problems.append("duplicate comps batch number: %d" % number)
            else:
                comps_files[number] = path

        identification_files = {}
        for path in sorted(root.glob("%s.identify-*.json" % source)):
            number = _batch_number(path, source, "identify")
            if number is None:
                problems.append(
                    "invalid identification artifact name: %s" % path.name)
            elif number in identification_files:
                problems.append(
                    "duplicate identification batch number: %d" % number)
            else:
                identification_files[number] = path

        expected_batches = ((len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE
                            if not problems or candidates else 0)
        batch_reports = []
        for number in range(1, expected_batches + 1):
            expected = candidates[(number - 1) * BATCH_SIZE:number * BATCH_SIZE]
            path = batch_files.get(number)
            comps_path = comps_files.get(number)
            identification_path = identification_files.get(number)
            if path is None:
                report = {
                    "batch": number,
                    "artifact": str(root / ("%s.appraisal-%d.json" % (source, number))),
                    "comps_artifact": str(comps_path) if comps_path else None,
                    "identification_artifact": (
                        str(identification_path) if identification_path else None),
                    "complete": False,
                    "candidate_count": len(expected),
                    "appraisal_count": None,
                    "comps_count": None,
                    "identification_count": None,
                    "listing_keys": [],
                    "error": "appraisal artifact is missing",
                }
            else:
                try:
                    results = _read_json(path)
                    comps_results = _read_json(comps_path) if comps_path is not None else None
                    needs_identification = (
                        isinstance(results, list)
                        and any(isinstance(row, dict)
                                and row.get("listing_category") == "minifigure"
                                for row in results)
                    )
                    if needs_identification and identification_path is None:
                        raise ValueError("identification artifact is missing")
                    identification_results = (
                        _read_json(identification_path)
                        if identification_path is not None else None)
                    report = dict(
                        synthesis_coverage(
                            expected,
                            results,
                            comps_results,
                            identification_results=identification_results,
                        ),
                        batch=number, artifact=str(path),
                        comps_artifact=str(comps_path) if comps_path else None,
                        identification_artifact=(
                            str(identification_path)
                            if identification_path else None),
                        comps_count=(len(comps_results)
                                    if isinstance(comps_results, list) else None),
                        identification_count=(
                            len(identification_results)
                            if isinstance(identification_results, list) else None),
                    )
                except ValueError as exc:
                    report = {
                        "batch": number, "artifact": str(path),
                        "comps_artifact": str(comps_path) if comps_path else None,
                        "identification_artifact": (
                            str(identification_path)
                            if identification_path else None),
                        "complete": False,
                        "candidate_count": len(expected), "appraisal_count": None,
                        "comps_count": None, "identification_count": None,
                        "listing_keys": [], "error": str(exc),
                    }
            if not report["complete"]:
                problems.append("appraisal batch %d: %s" % (number, report["error"]))
            batch_reports.append(report)

        extra_batches = sorted(set(batch_files) - set(range(1, expected_batches + 1)))
        if extra_batches:
            problems.append("unexpected appraisal batches: %s"
                            % ", ".join(map(str, extra_batches)))
        extra_comps_batches = sorted(set(comps_files) - set(range(1, expected_batches + 1)))
        if extra_comps_batches:
            problems.append("unexpected comps batches: %s"
                            % ", ".join(map(str, extra_comps_batches)))
        extra_identification_batches = sorted(
            set(identification_files) - set(range(1, expected_batches + 1)))
        if extra_identification_batches:
            problems.append("unexpected identification batches: %s"
                            % ", ".join(map(str, extra_identification_batches)))

        terminal = source_status in ("checked", "blocked")
        coverage_complete = not problems and len(batch_reports) == expected_batches
        sources.append({
            "source": source,
            "source_artifact": str(source_path),
            "source_status": source_status,
            "terminal": terminal,
            "candidate_count": len(candidates),
            "expected_appraisal_batches": expected_batches,
            "appraisal_batches": batch_reports,
            "coverage_complete": coverage_complete,
            "problems": problems,
        })

    return {
        "run_dir": str(root),
        "active_sources": planned,
        "active_source_count": len(planned),
        "terminal_source_count": sum(item["terminal"] for item in sources),
        "coverage_complete_source_count": sum(
            item["coverage_complete"] for item in sources),
        "orphan_identification_artifacts": orphan_identification_artifacts,
        "complete": (
            not orphan_identification_artifacts
            and all(item["terminal"] and item["coverage_complete"]
                    for item in sources)),
        "sources": sources,
    }
