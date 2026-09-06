"""Runtime contract for CourseCraft human-verification gates."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Dict, Mapping, Optional, Tuple


PROJECTION_RESOURCE = "data/human-verification.generated.json"
ACTOR_KINDS = frozenset({"artifact_agent", "human_ui"})
_GATE_KEYS = frozenset(
    {"id", "table", "field", "artifactIds", "owner", "clearOn", "prerequisites"}
)
_PREREQUISITE_KEYS = frozenset({"kind", "ref", "required_state"})


class HumanVerificationError(ValueError):
    """A human-verification request violated the packaged contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


class HumanVerificationPreconditionError(HumanVerificationError):
    """One or more declared prerequisites are not satisfied."""

    def __init__(self, gate_id: str, missing: Tuple[dict[str, str], ...]):
        self.gate_id = gate_id
        self.missing = missing
        refs = ", ".join(f"{item['kind']}:{item['ref']}" for item in missing)
        super().__init__(
            "HV_PREREQUISITE",
            f"gate {gate_id!r} prerequisites are not passed, in declared order: {refs}",
        )


@dataclass(frozen=True)
class HumanVerificationGate:
    id: str
    table: str
    field: str
    artifact_ids: Tuple[str, ...]
    owner: str
    clear_on: Tuple[str, ...]
    prerequisites: Tuple[dict[str, str], ...]


@dataclass(frozen=True)
class HumanVerificationIndex:
    by_id: Mapping[str, HumanVerificationGate]
    by_artifact_id: Mapping[str, Tuple[HumanVerificationGate, ...]]
    by_table_field: Mapping[Tuple[str, str], HumanVerificationGate]


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HumanVerificationError("HV_PROJECTION", f"{label} must be a non-empty string")
    return value


def _require_strings(value: Any, label: str, *, non_empty: bool = False) -> Tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise HumanVerificationError("HV_PROJECTION", f"{label} must be an array of strings")
    if non_empty and not value:
        raise HumanVerificationError("HV_PROJECTION", f"{label} must not be empty")
    if len(set(value)) != len(value):
        raise HumanVerificationError("HV_PROJECTION", f"{label} contains duplicates")
    return tuple(value)


def build_human_verification_index(raw: Any) -> HumanVerificationIndex:
    """Validate and index the packaged mechanical projection."""
    if not isinstance(raw, list) or not raw:
        raise HumanVerificationError(
            "HV_PROJECTION", "human-verification projection must be a non-empty array"
        )

    by_id: Dict[str, HumanVerificationGate] = {}
    by_artifact: Dict[str, list[HumanVerificationGate]] = {}
    by_table_field: Dict[Tuple[str, str], HumanVerificationGate] = {}
    for position, item in enumerate(raw):
        if not isinstance(item, dict) or frozenset(item) != _GATE_KEYS:
            raise HumanVerificationError(
                "HV_PROJECTION", f"gate at index {position} has an invalid schema"
            )
        gate_id = _require_string(item["id"], f"gate[{position}].id")
        table = _require_string(item["table"], f"gate {gate_id}.table")
        field = _require_string(item["field"], f"gate {gate_id}.field")
        artifact_ids = _require_strings(
            item["artifactIds"], f"gate {gate_id}.artifactIds", non_empty=True
        )
        owner = _require_string(item["owner"], f"gate {gate_id}.owner")
        clear_on = _require_strings(item["clearOn"], f"gate {gate_id}.clearOn")
        raw_prerequisites = item["prerequisites"]
        if not isinstance(raw_prerequisites, list):
            raise HumanVerificationError(
                "HV_PROJECTION", f"gate {gate_id}.prerequisites must be an array"
            )
        prerequisites = []
        for prereq_position, prerequisite in enumerate(raw_prerequisites):
            if not isinstance(prerequisite, dict) or frozenset(prerequisite) != _PREREQUISITE_KEYS:
                raise HumanVerificationError(
                    "HV_PROJECTION",
                    f"gate {gate_id}.prerequisites[{prereq_position}] has an invalid schema",
                )
            kind = _require_string(prerequisite["kind"], "prerequisite.kind")
            ref = _require_string(prerequisite["ref"], "prerequisite.ref")
            required_state = _require_string(
                prerequisite["required_state"], "prerequisite.required_state"
            )
            if kind not in {"gate", "check", "walkthrough"} or required_state != "passed":
                raise HumanVerificationError(
                    "HV_PROJECTION", f"gate {gate_id} has an unsupported prerequisite"
                )
            prerequisites.append(
                {"kind": kind, "ref": ref, "required_state": required_state}
            )
        if gate_id in by_id:
            raise HumanVerificationError("HV_PROJECTION", f"duplicate gate id {gate_id!r}")
        table_field = (table, field)
        if table_field in by_table_field:
            raise HumanVerificationError(
                "HV_PROJECTION", f"duplicate gate field {table}.{field}"
            )
        gate = HumanVerificationGate(
            id=gate_id,
            table=table,
            field=field,
            artifact_ids=artifact_ids,
            owner=owner,
            clear_on=clear_on,
            prerequisites=tuple(prerequisites),
        )
        by_id[gate_id] = gate
        by_table_field[table_field] = gate
        for artifact_id in artifact_ids:
            by_artifact.setdefault(artifact_id, []).append(gate)

    return HumanVerificationIndex(
        by_id=dict(sorted(by_id.items())),
        by_artifact_id={
            artifact_id: tuple(sorted(gates, key=lambda gate: gate.id))
            for artifact_id, gates in sorted(by_artifact.items())
        },
        by_table_field=by_table_field,
    )


@lru_cache(maxsize=1)
def human_verification_projection() -> list[dict[str, Any]]:
    """Read the generated projection from the installed package."""
    resource = files("coursecraft_cli").joinpath(PROJECTION_RESOURCE)
    try:
        raw = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HumanVerificationError(
            "HV_RESOURCE", f"cannot read packaged {PROJECTION_RESOURCE}: {error}"
        ) from None
    build_human_verification_index(raw)
    return raw


@lru_cache(maxsize=1)
def human_verification_index() -> HumanVerificationIndex:
    return build_human_verification_index(human_verification_projection())


def human_verification_clear_targets(
    artifact_id: str,
    table: str,
    event: str,
    gate_index: Optional[HumanVerificationIndex] = None,
) -> Tuple[str, ...]:
    """Resolve gate fields cleared by one event for one record-local artifact."""
    index = gate_index or human_verification_index()
    return tuple(
        gate.field
        for gate in index.by_artifact_id.get(artifact_id, ())
        if gate.table == table and event in gate.clear_on
    )


def is_human_verification_field(
    table: str,
    field: str,
    gate_index: Optional[HumanVerificationIndex] = None,
) -> bool:
    """Return whether the generated active registry owns this table-qualified field."""
    index = gate_index or human_verification_index()
    return (table, field) in index.by_table_field


def parse_requested_state(value: str) -> bool:
    normalized = value.strip().lower() if isinstance(value, str) else ""
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise HumanVerificationError(
        "HV_STATE", "--requested-state must be exactly true or false"
    )


def resolve_human_verification_request(
    *,
    actor_kind: str,
    artifact_id: str,
    gate_id: str,
    record_id: str,
    requested_state: bool,
    caller_agent: Optional[str],
    gate_index: Optional[HumanVerificationIndex] = None,
) -> HumanVerificationGate:
    """Authorize request identity before any external read or mutation."""
    if actor_kind not in ACTOR_KINDS:
        raise HumanVerificationError(
            "HV_ACTOR_KIND", "--actor-kind must be artifact_agent or human_ui"
        )
    if not isinstance(requested_state, bool):
        raise HumanVerificationError("HV_STATE", "requested state must be boolean")
    if not isinstance(record_id, str) or not record_id.strip():
        raise HumanVerificationError("HV_RECORD_ID", "--record-id must not be empty")
    index = gate_index or human_verification_index()
    gate = index.by_id.get(gate_id)
    if gate is None:
        raise HumanVerificationError("HV_GATE", f"unknown gate {gate_id!r}")
    if artifact_id not in gate.artifact_ids:
        raise HumanVerificationError(
            "HV_ARTIFACT_GATE",
            f"artifact {artifact_id!r} is not bound to gate {gate_id!r}",
        )
    if actor_kind == "artifact_agent":
        if not caller_agent:
            raise HumanVerificationError(
                "HV_CALLER_AGENT_REQUIRED",
                "--caller-agent is required for actor kind artifact_agent",
            )
        if caller_agent != gate.owner:
            raise HumanVerificationError(
                "HV_CALLER_AGENT",
                f"caller {caller_agent!r} does not own gate {gate_id!r}",
            )
    elif caller_agent is not None:
        raise HumanVerificationError(
            "HV_CALLER_AGENT_FORBIDDEN",
            "--caller-agent is forbidden for actor kind human_ui",
        )
    return gate


def evaluate_human_verification_write(
    actor_kind: str,
    artifact_id: str,
    gate_id: str,
    caller_agent: Optional[str],
    record_id: str,
    requested_state: bool,
    current_fields: Mapping[str, Any],
    prerequisite_states: Mapping[Tuple[str, str], bool],
    gate_index: Optional[HumanVerificationIndex] = None,
) -> dict[str, Any]:
    """Return one normalized mutation proposal without performing the write."""
    gate = resolve_human_verification_request(
        actor_kind=actor_kind,
        artifact_id=artifact_id,
        gate_id=gate_id,
        record_id=record_id,
        requested_state=requested_state,
        caller_agent=caller_agent,
        gate_index=gate_index,
    )
    if requested_state:
        missing = tuple(
            prerequisite
            for prerequisite in gate.prerequisites
            if prerequisite_states.get((prerequisite["kind"], prerequisite["ref"]))
            is not True
        )
        if missing:
            raise HumanVerificationPreconditionError(gate.id, missing)
    current_state = current_fields.get(gate.field) is True
    return {
        "actor_kind": actor_kind,
        "artifact_slug": artifact_id,
        "gate_id": gate.id,
        "record_id": record_id,
        "table": gate.table,
        "field": gate.field,
        "requested_state": requested_state,
        "changed": current_state != requested_state,
        "persisted_state": current_state if current_state == requested_state else requested_state,
    }
