"""Adapter for `crowdgen tasks list` records.

Evidence state (2026-09-03): CrowdGen (Appen) work appears only after an
account is shortlisted for a project, and no authenticated capture of a
`projects/available` record exists yet — registration is Kasada-blocked for
automation browser sessions on this network and the remaining sign-up steps
(mobile -> address/agreements -> payout -> government-ID) are human gates.
The `crowdgen` CLI therefore returns `[]` (provably-empty dashboard) and
refuses to map any non-empty payload whose shape is unobserved
(crowdgen_cli/parsers.py).

Consequences for this adapter:

  - `RAW_KEYS` is empty: no raw record field has ever been observed, so no
    key can be listed as required or mapped.
  - `to_task(raw)` refuses to map: an empty record is a contradiction and a
    non-empty record has an unobserved shape. Both raise a `ClientError` that
    tells the caller to record a live fixture first. This keeps the
    evidence-backed rule: no invented task fields, no guessed ids or prices.
    When the first real record is captured, replace the refusal with the real
    mapping (mirroring microworkers.py/humanrail.py) and fill `RAW_KEYS`.
  - `ADAPTERS` registration in `adapters/__init__.py` is intentionally left to
    the parent (this task forbids editing it): until then, an `ok` crowdgen
    envelope with tasks fails loudly at merge time, which is the correct state
    while no record shape is known.
"""

from __future__ import annotations

from cli_tools_shared.exceptions import ClientError

from .mapped import MappedTask

SITE = "crowdgen"
# No raw record field has ever been observed; see module docstring.
RAW_KEYS = ()


def to_task(raw: dict) -> MappedTask:
    if not raw:
        raise ClientError("crowdgen record is empty; a task record must be a dict")
    raise ClientError(
        "crowdgen record shape has not been validated against a live capture; "
        "mapping is refused until a real `crowdgen tasks list` record is "
        "recorded under a fixture and adapters/crowdgen.py is finalized"
    )
