"""Generic CourseCraft human-verification mutation command."""
from __future__ import annotations

from typing import Optional

import typer
from cli_tools_shared.output import command

from ..client import get_client
from ..human_verification import (
    HumanVerificationError,
    HumanVerificationGate,
    evaluate_human_verification_write,
    human_verification_index,
    resolve_human_verification_request,
)
from ..output import print_json


app = typer.Typer(help="Set or clear a canonical human-verification gate")

COMMAND_CREDENTIALS = {
    "set": ["custom"],
    "clear": ["custom"],
}

_WALKTHROUGH_FIELDS = {"automated_walkthrough": "Walkthrough Test Complete"}


def _check_passed(value: object) -> bool:
    return isinstance(value, str) and value.lstrip().startswith("PASS")


def _prerequisite_states(
    gate: HumanVerificationGate,
    fields: dict,
) -> dict[tuple[str, str], bool]:
    states: dict[tuple[str, str], bool] = {}
    index = human_verification_index()
    for prerequisite in gate.prerequisites:
        kind = prerequisite["kind"]
        ref = prerequisite["ref"]
        if kind == "check":
            passed = _check_passed(fields.get(ref))
        elif kind == "walkthrough":
            walkthrough_field = _WALKTHROUGH_FIELDS.get(ref)
            if walkthrough_field is None:
                raise HumanVerificationError(
                    "HV_PREREQUISITE_REF", f"unknown walkthrough prerequisite {ref!r}"
                )
            passed = fields.get(walkthrough_field) is True
        else:
            referenced_gate = index.by_id.get(ref)
            if referenced_gate is None or referenced_gate.table != gate.table:
                raise HumanVerificationError(
                    "HV_PREREQUISITE_REF", f"invalid same-record gate prerequisite {ref!r}"
                )
            passed = fields.get(referenced_gate.field) is True
        states[(kind, ref)] = passed
    return states


def _mutate_human_verification(
    *,
    record_id: str,
    artifact: str,
    gate_id: str,
    actor: str,
    caller_agent: Optional[str],
    state: bool,
) -> None:
    actor_kind = actor.replace("-", "_")
    gate = resolve_human_verification_request(
        actor_kind=actor_kind,
        artifact_id=artifact,
        gate_id=gate_id,
        record_id=record_id,
        requested_state=state,
        caller_agent=caller_agent,
    )

    client = get_client()
    record = client.get_record(gate.table, record_id)
    if not record:
        raise HumanVerificationError(
            "HV_RECORD_NOT_FOUND", f"{gate.table} record not found: {record_id}"
        )
    current_fields = record.get("fields", {})
    proposal = evaluate_human_verification_write(
        actor_kind=actor_kind,
        artifact_id=artifact,
        gate_id=gate_id,
        caller_agent=caller_agent,
        record_id=record_id,
        requested_state=state,
        current_fields=current_fields,
        prerequisite_states=_prerequisite_states(gate, current_fields) if state else {},
    )
    if proposal["changed"]:
        persisted = client.update_record(gate.table, record_id, {gate.field: state})
        persisted_fields = persisted.get("fields", {}) if isinstance(persisted, dict) else {}
        if (persisted_fields.get(gate.field) is True) != state:
            raise HumanVerificationError(
                "HV_READBACK", f"{gate.table}.{gate.field} did not persist requested state"
            )
    print_json(proposal)


def _record_id_argument() -> str:
    return typer.Argument(..., help="Airtable record ID")


def _artifact_option() -> str:
    return typer.Option(..., "--artifact", help="Canonical artifact slug")


def _gate_option() -> str:
    return typer.Option(..., "--gate", help="Canonical human-verification gate ID")


def _actor_option() -> str:
    return typer.Option(..., "--actor", help="Mutation actor: artifact-agent or human-ui")


def _caller_agent_option() -> Optional[str]:
    return typer.Option(
        None,
        "--caller-agent",
        help="Required artifact owner for artifact-agent; forbidden for human-ui",
    )


@app.command("set")
@command
def set_human_verification(
    record_id: str = _record_id_argument(),
    artifact: str = _artifact_option(),
    gate_id: str = _gate_option(),
    actor: str = _actor_option(),
    caller_agent: Optional[str] = _caller_agent_option(),
):
    """Set one gate after authorization and prerequisite checks."""
    _mutate_human_verification(
        record_id=record_id,
        artifact=artifact,
        gate_id=gate_id,
        actor=actor,
        caller_agent=caller_agent,
        state=True,
    )


@app.command("clear")
@command
def clear_human_verification(
    record_id: str = _record_id_argument(),
    artifact: str = _artifact_option(),
    gate_id: str = _gate_option(),
    actor: str = _actor_option(),
    caller_agent: Optional[str] = _caller_agent_option(),
):
    """Clear one gate after authorization checks."""
    _mutate_human_verification(
        record_id=record_id,
        artifact=artifact,
        gate_id=gate_id,
        actor=actor,
        caller_agent=caller_agent,
        state=False,
    )
