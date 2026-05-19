"""Static health-check engine for n8n workflows.

Runs a data-driven registry of node-level checks against a workflow JSON to
catch configuration problems BEFORE activation: broken loadOptions, missing
required parameters, deleted credentials, version mismatches, dead webhook
paths, orphan pinData, etc.

Public surface:
    run_health_checks(workflow, api, *, node_name_filter=None, strict=False)
        -> list[Finding]

A `Finding` is the unified output type. `severity` is "fail" or "warn".
Checks are registered as `Check` entries in `CHECK_REGISTRY` (data-driven
— adding a new check is one entry in that list, not an if/else branch).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Finding:
    """A single health-check result for one node (or workflow-level concern)."""
    node: str
    node_id: str
    check: str
    severity: str  # "fail" or "warn"
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Check:
    """A registered health check.

    Attributes:
        id: Stable identifier (used as the `check` field on Findings).
        name: Human-readable name.
        severity: Default severity emitted by this check ("fail" or "warn").
        run: Callable(workflow, api) -> list[Finding].
    """
    id: str
    name: str
    severity: str
    run: Callable[[Dict, Any], List[Finding]]


# -- Helpers ----------------------------------------------------------------

def _node_id(node: Dict) -> str:
    return str(node.get("id") or "")


def _node_name(node: Dict) -> str:
    return str(node.get("name") or "")


def _finding(node: Dict, check_id: str, severity: str, message: str) -> Finding:
    return Finding(
        node=_node_name(node),
        node_id=_node_id(node),
        check=check_id,
        severity=severity,
        message=message,
    )


def _walk_load_options_props(
    properties: List[Dict],
    prefix: str = "parameters",
    ancestor_display_options: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Walk a node schema's properties recursively, yielding each property
    whose typeOptions exposes loadOptionsMethod / loadOptionsDependsOn, or
    whose type is resourceLocator.

    Each yielded entry is a dict with keys:
        path: dotted parameter path (e.g., "parameters.options.userIds")
        prop: the raw property dict
        ancestors: list of display_options dicts from each enclosing collection,
                   used to evaluate visibility against the top-level node params.
    """
    out: List[Dict] = []
    ancestors = list(ancestor_display_options or [])
    for p in properties:
        name = p.get("name") or ""
        path = f"{prefix}.{name}" if name else prefix
        type_options = p.get("typeOptions") or {}
        if (
            type_options.get("loadOptionsMethod")
            or type_options.get("loadOptionsDependsOn")
            or p.get("type") == "resourceLocator"
        ):
            out.append({"path": path, "prop": p, "ancestors": ancestors})
        # Recurse into collection-shaped properties, carrying THIS prop's display_options
        # forward so children inherit visibility from the wrapper.
        ptype = p.get("type")
        next_ancestors = ancestors + ([p.get("displayOptions")] if p.get("displayOptions") else [])
        if ptype in ("collection",):
            for sub in p.get("options") or []:
                if isinstance(sub, dict) and "name" in sub and "type" in sub:
                    out.extend(_walk_load_options_props([sub], path, next_ancestors))
        elif ptype == "fixedCollection":
            for opt in p.get("options") or []:
                if isinstance(opt, dict) and "values" in opt:
                    out.extend(
                        _walk_load_options_props(
                            opt["values"],
                            f"{path}.{opt.get('name', '?')}",
                            next_ancestors,
                        )
                    )
    return out


def _display_options_match(
    display_options: Optional[Dict],
    current_params: Dict,
) -> bool:
    """True if the property is visible given the current parameter values.

    n8n's displayOptions has `show` (must match all) and `hide` (must NOT match any).
    Each is a dict of param-name -> list of allowed values.
    """
    if not display_options:
        return True
    show = display_options.get("show") or {}
    hide = display_options.get("hide") or {}
    for k, allowed in show.items():
        actual = current_params.get(k)
        if isinstance(allowed, list):
            if actual not in allowed:
                # Lists: if the param itself is a list, treat as match if any overlap
                if isinstance(actual, list) and any(a in allowed for a in actual):
                    continue
                return False
        else:
            if actual != allowed:
                return False
    for k, disallowed in hide.items():
        actual = current_params.get(k)
        if isinstance(disallowed, list):
            if actual in disallowed:
                return False
            if isinstance(actual, list) and any(a in disallowed for a in actual):
                return False
        else:
            if actual == disallowed:
                return False
    return True


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _merge_schema_defaults(schema: Dict, current_params: Dict) -> Dict:
    """Return a copy of `current_params` with top-level schema defaults filled in
    for any property the node doesn't explicitly set.

    n8n's loadOptions endpoint requires display-gated parameters to be present —
    e.g. `authentication: 'accessToken'` to gate a `slackApi` credential. The
    workflow JSON omits values that match the default, so we have to reconstitute
    them before calling the endpoint, exactly like the editor UI does.

    Only top-level scalar properties are merged. Collection defaults are skipped
    to avoid synthesizing structures the user never opted into.
    """
    merged = dict(current_params or {})
    for p in schema.get("properties") or []:
        name = p.get("name") or ""
        if not name or name in merged:
            continue
        ptype = p.get("type")
        if ptype in ("collection", "fixedCollection"):
            continue
        if "default" in p:
            merged[name] = p["default"]
    return merged


def _get_nested(d: Dict, dotted_path: str) -> Any:
    """Resolve a dotted path relative to a parameters dict.

    `dotted_path` is like 'parameters.options.userIds' — the first segment
    'parameters' is stripped because we're already inside the params dict.
    """
    parts = dotted_path.split(".")
    if parts and parts[0] == "parameters":
        parts = parts[1:]
    cur: Any = d
    for part in parts:
        if not isinstance(cur, dict):
            return None
        if part not in cur:
            return None
        cur = cur[part]
    return cur


# -- Schema cache -----------------------------------------------------------

class _SchemaCache:
    """Caches node-type schemas + credential list within a single run."""

    def __init__(self, api):
        self.api = api
        self._schemas: Dict[str, Optional[Dict]] = {}
        self._credentials: Optional[List[Dict]] = None

    def get_schema(self, node_type: str) -> Optional[Dict]:
        if node_type not in self._schemas:
            self._schemas[node_type] = self.api.get_node_type(node_type)
        return self._schemas[node_type]

    def list_credentials(self) -> List[Dict]:
        if self._credentials is None:
            self._credentials = self.api.list_credentials()
        return self._credentials

    def credential_by_id(self, cred_id: str) -> Optional[Dict]:
        for c in self.list_credentials():
            if c.get("id") == cred_id:
                return c
        return None


# Module-level cache, reset by run_health_checks
_CACHE: Optional[_SchemaCache] = None


def _cache() -> _SchemaCache:
    if _CACHE is None:
        raise RuntimeError("Health checks must run via run_health_checks()")
    return _CACHE


# -- Trigger detection -------------------------------------------------------

_TRIGGER_TYPE_HINTS = (
    "trigger",
    ".webhook",
    ".formTrigger",
    ".cron",
    ".scheduleTrigger",
    ".manualTrigger",
    ".chatTrigger",
    ".executeWorkflowTrigger",
)


def _is_trigger(node: Dict) -> bool:
    schema = _cache().get_schema(node.get("type", ""))
    if schema:
        group = schema.get("group") or []
        if isinstance(group, list) and "trigger" in group:
            return True
        # polling/event triggers sometimes only set this:
        if schema.get("polling") or schema.get("eventTriggerDescription"):
            return True
    ntype = (node.get("type") or "").lower()
    return any(hint in ntype for hint in _TRIGGER_TYPE_HINTS)


# -- Checks -----------------------------------------------------------------

def check_load_options_resolves(workflow: Dict, api) -> List[Finding]:
    """Call each loadOptionsMethod on each node and report non-2xx / error bodies."""
    findings: List[Finding] = []
    for node in workflow.get("nodes") or []:
        ntype = node.get("type") or ""
        type_version = node.get("typeVersion") or 1
        schema = _cache().get_schema(ntype)
        if not schema:
            continue
        props = _walk_load_options_props(schema.get("properties") or [])
        for entry in props:
            prop = entry["prop"]
            path = entry["path"]
            type_options = prop.get("typeOptions") or {}
            method = type_options.get("loadOptionsMethod")
            if not method:
                # resourceLocator without an explicit loadOptionsMethod uses its
                # own resource-locator endpoint — skip for now (handled by n8n UI
                # but not part of the options-request contract).
                continue
            # Visibility gate — evaluate against the node's top-level params,
            # which is where 'resource', 'operation', etc. live. We require BOTH
            # the prop's own displayOptions AND every ancestor (wrapper collection)
            # displayOptions to match.
            top_params = node.get("parameters") or {}
            visible = _display_options_match(prop.get("displayOptions"), top_params)
            if visible:
                for anc in entry.get("ancestors") or []:
                    if not _display_options_match(anc, top_params):
                        visible = False
                        break
            if not visible:
                continue
            try:
                merged_params = _merge_schema_defaults(
                    schema, node.get("parameters") or {}
                )
                resp = api.dynamic_options_request(
                    node_type=ntype,
                    type_version=type_version,
                    path=path,
                    method_name=method,
                    current_node_parameters=merged_params,
                    credentials=node.get("credentials") or {},
                )
            except Exception as e:
                findings.append(_finding(
                    node, "load_options_resolves", "fail",
                    f"{path} ({method}): request failed: {e}",
                ))
                continue
            status = resp.get("_status_code", 0)
            body = resp.get("_body") or {}
            if status < 200 or status >= 300:
                msg = body.get("message") if isinstance(body, dict) else str(body)
                findings.append(_finding(
                    node, "load_options_resolves", "fail",
                    f"{path} ({method}): HTTP {status}: {msg}",
                ))
                continue
            # Some endpoints return 200 but signal error in body
            if isinstance(body, dict):
                err = body.get("error") or body.get("errorMessage")
                if err:
                    findings.append(_finding(
                        node, "load_options_resolves", "fail",
                        f"{path} ({method}): {err}",
                    ))
    return findings


def check_required_params_set(workflow: Dict, api) -> List[Finding]:
    """Every required: true property whose displayOptions match must have a value."""
    findings: List[Finding] = []

    def walk(props: List[Dict], current_params: Dict, prefix: str = "parameters"):
        for p in props:
            name = p.get("name") or ""
            path = f"{prefix}.{name}" if name else prefix
            if not _display_options_match(p.get("displayOptions"), current_params):
                continue
            if p.get("required") and name:
                value = current_params.get(name)
                if _is_empty(value):
                    # n8n applies the schema 'default' when the parameter is omitted,
                    # so a non-empty default means the field is effectively set.
                    default_val = p.get("default")
                    if _is_empty(default_val):
                        findings.append(_finding(
                            node, "required_params_set", "fail",
                            f"required parameter '{path}' is empty or missing",
                        ))
            # Recurse into collections
            ptype = p.get("type")
            if ptype == "collection":
                sub_params = current_params.get(name) if name else current_params
                if isinstance(sub_params, dict):
                    sub_options = p.get("options") or []
                    walk(sub_options, sub_params, path)
            elif ptype == "fixedCollection":
                sub_params = current_params.get(name) if name else current_params
                if isinstance(sub_params, dict):
                    for opt in p.get("options") or []:
                        if isinstance(opt, dict) and "values" in opt:
                            opt_name = opt.get("name") or ""
                            child_params = sub_params.get(opt_name) or {}
                            if isinstance(child_params, dict):
                                walk(opt["values"], child_params, f"{path}.{opt_name}")

    for node in workflow.get("nodes") or []:
        schema = _cache().get_schema(node.get("type", ""))
        if not schema:
            continue
        walk(
            schema.get("properties") or [],
            node.get("parameters") or {},
        )
    return findings


def check_credentials_exist(workflow: Dict, api) -> List[Finding]:
    """Every credential referenced by a node must exist on the server."""
    findings: List[Finding] = []
    for node in workflow.get("nodes") or []:
        creds = node.get("credentials") or {}
        for cred_type, cred_ref in creds.items():
            if not isinstance(cred_ref, dict):
                continue
            cred_id = cred_ref.get("id")
            if not cred_id:
                findings.append(_finding(
                    node, "credentials_exist", "fail",
                    f"credential ref for type '{cred_type}' has no id",
                ))
                continue
            found = _cache().credential_by_id(str(cred_id))
            if not found:
                findings.append(_finding(
                    node, "credentials_exist", "fail",
                    f"credential id={cred_id} (type={cred_type}) does not exist",
                ))
    return findings


_FULL_ACCESS_CRED_NODE_TYPES = {
    # n8n-core gives these nodes 'fullAccess' — they accept ANY credential type
    # via nodeCredentialType, so the static "type listed in schema" check is invalid.
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.httpRequestTool",
}


def check_credential_type_matches(workflow: Dict, api) -> List[Finding]:
    """Each referenced credential's actual type must be accepted by the node schema."""
    findings: List[Finding] = []
    for node in workflow.get("nodes") or []:
        if node.get("type") in _FULL_ACCESS_CRED_NODE_TYPES:
            continue
        creds = node.get("credentials") or {}
        if not creds:
            continue
        schema = _cache().get_schema(node.get("type", ""))
        if not schema:
            continue
        accepted = {c.get("name") for c in (schema.get("credentials") or []) if isinstance(c, dict)}
        if not accepted:
            continue
        for cred_type, cred_ref in creds.items():
            if cred_type not in accepted:
                findings.append(_finding(
                    node, "credential_type_matches", "fail",
                    f"credential type '{cred_type}' is not accepted by node schema "
                    f"(accepted: {sorted(accepted)})",
                ))
                continue
            if not isinstance(cred_ref, dict):
                continue
            cred_id = cred_ref.get("id")
            if not cred_id:
                continue
            actual = _cache().credential_by_id(str(cred_id))
            if actual and actual.get("type") and actual["type"] != cred_type:
                findings.append(_finding(
                    node, "credential_type_matches", "fail",
                    f"credential id={cred_id} is type '{actual['type']}' "
                    f"but node references it as '{cred_type}'",
                ))
    return findings


def check_type_version_valid(workflow: Dict, api) -> List[Finding]:
    """Node typeVersion must be within the schema's version range."""
    findings: List[Finding] = []
    for node in workflow.get("nodes") or []:
        schema = _cache().get_schema(node.get("type", ""))
        if not schema:
            continue
        node_version = node.get("typeVersion")
        if node_version is None:
            continue
        # n8n exposes either 'defaultVersion' or a 'version' field (number or list).
        schema_versions = schema.get("version")
        default_version = schema.get("defaultVersion")
        candidates: List[float] = []
        if isinstance(schema_versions, list):
            for v in schema_versions:
                try:
                    candidates.append(float(v))
                except (TypeError, ValueError):
                    pass
        elif schema_versions is not None:
            try:
                candidates.append(float(schema_versions))
            except (TypeError, ValueError):
                pass
        if default_version is not None:
            try:
                candidates.append(float(default_version))
            except (TypeError, ValueError):
                pass
        if not candidates:
            continue
        max_v = max(candidates)
        min_v = min(candidates)
        try:
            nv = float(node_version)
        except (TypeError, ValueError):
            findings.append(_finding(
                node, "type_version_valid", "fail",
                f"typeVersion '{node_version}' is not numeric",
            ))
            continue
        if nv < min_v:
            findings.append(_finding(
                node, "type_version_valid", "fail",
                f"typeVersion {nv} is below schema min {min_v}",
            ))
        # Above max is OK (newer than current) per spec — do not flag.
    return findings


def check_subworkflow_refs_valid(workflow: Dict, api) -> List[Finding]:
    """executeWorkflow nodes must reference an existing AND active sub-workflow."""
    findings: List[Finding] = []
    # Only the dispatcher type — executeWorkflowTrigger is the RECEIVING side
    # and has no workflowId to validate.
    sub_types = {"n8n-nodes-base.executeWorkflow"}
    for node in workflow.get("nodes") or []:
        if node.get("type") not in sub_types:
            continue
        params = node.get("parameters") or {}
        # workflowId may be a resourceLocator { __rl, value, mode } or a plain str
        wf_id_param = params.get("workflowId")
        wf_id = None
        if isinstance(wf_id_param, dict):
            wf_id = wf_id_param.get("value")
        else:
            wf_id = wf_id_param
        if not wf_id:
            findings.append(_finding(
                node, "subworkflow_refs_valid", "fail",
                "executeWorkflow node has no workflowId",
            ))
            continue
        try:
            sub_wf = api.get_workflow(str(wf_id))
        except Exception as e:
            findings.append(_finding(
                node, "subworkflow_refs_valid", "fail",
                f"referenced workflow id={wf_id} could not be fetched: {e}",
            ))
            continue
        if not sub_wf:
            findings.append(_finding(
                node, "subworkflow_refs_valid", "fail",
                f"referenced workflow id={wf_id} does not exist",
            ))
            continue
        if not sub_wf.get("active"):
            findings.append(_finding(
                node, "subworkflow_refs_valid", "fail",
                f"referenced workflow '{sub_wf.get('name')}' (id={wf_id}) is not active",
            ))
    return findings


def check_webhook_path_unique(workflow: Dict, api) -> List[Finding]:
    """Webhook/trigger nodes with the same (path, httpMethod) within the workflow."""
    findings: List[Finding] = []
    seen: Dict[tuple, List[Dict]] = {}
    for node in workflow.get("nodes") or []:
        ntype = (node.get("type") or "").lower()
        if "webhook" not in ntype and "formtrigger" not in ntype:
            continue
        params = node.get("parameters") or {}
        path = params.get("path") or node.get("webhookId")
        method = params.get("httpMethod") or "GET"
        if not path:
            continue
        key = (str(path), str(method).upper())
        seen.setdefault(key, []).append(node)
    for (path, method), nodes in seen.items():
        if len(nodes) > 1:
            names = ", ".join(_node_name(n) for n in nodes)
            for n in nodes:
                findings.append(_finding(
                    n, "webhook_path_unique", "fail",
                    f"duplicate webhook path '{path}' method={method} (also on: {names})",
                ))
    return findings


def check_non_trigger_connected(workflow: Dict, api) -> List[Finding]:
    """Non-trigger nodes must have at least one incoming connection on any
    connection type (main, ai_tool, ai_languageModel, ai_memory, etc.).

    AI sub-nodes (tools, models, memories) connect to their parent agent
    via reverse connections rooted at the SUB-NODE, not the agent. So we
    treat any node that appears as a source in `connections` as also
    being connected (for the purpose of this check), unless it's clearly
    orphaned.
    """
    findings: List[Finding] = []
    connections = workflow.get("connections") or {}
    destinations: set = set()
    sources: set = set()
    for source, conn_types in connections.items():
        if source:
            sources.add(source)
        if not isinstance(conn_types, dict):
            continue
        for _conn_name, branches in conn_types.items():
            if not isinstance(branches, list):
                continue
            for branch in branches:
                if not isinstance(branch, list):
                    continue
                for link in branch:
                    if isinstance(link, dict) and link.get("node"):
                        destinations.add(link["node"])
    connected = destinations | sources
    for node in workflow.get("nodes") or []:
        if _is_trigger(node):
            continue
        if _node_name(node) not in connected:
            findings.append(_finding(
                node, "non_trigger_connected", "warn",
                "non-trigger node has no incoming connection",
            ))
    return findings


_EXPR_NODE_REF = re.compile(r"""\$\(\s*['"]([^'"]+)['"]\s*\)|\$node\[\s*['"]([^'"]+)['"]\s*\]""")


def check_expression_node_refs_resolve(workflow: Dict, api) -> List[Finding]:
    """`$('Node Name')` or `$node["Name"]` references in expressions must resolve."""
    findings: List[Finding] = []
    node_names = {_node_name(n) for n in workflow.get("nodes") or []}

    def scan(value: Any, source_node: Dict, where: str):
        if isinstance(value, str):
            if not value.startswith("="):
                return
            for m in _EXPR_NODE_REF.finditer(value):
                ref = m.group(1) or m.group(2)
                if ref and ref not in node_names:
                    findings.append(_finding(
                        source_node, "expression_node_refs_resolve", "warn",
                        f"expression at {where} references unknown node '{ref}'",
                    ))
        elif isinstance(value, dict):
            for k, v in value.items():
                scan(v, source_node, f"{where}.{k}")
        elif isinstance(value, list):
            for i, v in enumerate(value):
                scan(v, source_node, f"{where}[{i}]")

    for node in workflow.get("nodes") or []:
        scan(node.get("parameters") or {}, node, "parameters")
    return findings


def check_pin_data_orphans(workflow: Dict, api) -> List[Finding]:
    """workflow.pinData keys that don't match any current node name."""
    findings: List[Finding] = []
    pin = workflow.get("pinData") or {}
    if not pin:
        return findings
    names = {_node_name(n) for n in workflow.get("nodes") or []}
    for key in pin.keys():
        if key not in names:
            # Synthesize a workflow-level finding (no specific node)
            findings.append(Finding(
                node=key,
                node_id="",
                check="pin_data_orphans",
                severity="warn",
                message=f"pinData references node '{key}' which is not in the workflow",
            ))
    return findings


# -- Registry ---------------------------------------------------------------

CHECK_REGISTRY: List[Check] = [
    Check("load_options_resolves",          "Load options method resolves",         "fail", check_load_options_resolves),
    Check("required_params_set",            "Required parameters set",              "fail", check_required_params_set),
    Check("credentials_exist",              "Credentials exist on server",          "fail", check_credentials_exist),
    Check("credential_type_matches",        "Credential type matches node schema",  "fail", check_credential_type_matches),
    Check("type_version_valid",             "typeVersion within schema range",      "fail", check_type_version_valid),
    Check("subworkflow_refs_valid",         "Sub-workflow references valid",        "fail", check_subworkflow_refs_valid),
    Check("webhook_path_unique",            "Webhook paths unique",                 "fail", check_webhook_path_unique),
    Check("non_trigger_connected",          "Non-trigger nodes connected",          "warn", check_non_trigger_connected),
    Check("expression_node_refs_resolve",   "Expression node refs resolve",         "warn", check_expression_node_refs_resolve),
    Check("pin_data_orphans",               "pinData keys reference existing nodes","warn", check_pin_data_orphans),
]


# -- Public API -------------------------------------------------------------

def run_health_checks(
    workflow: Dict,
    api,
    *,
    node_name_filter: Optional[str] = None,
    strict: bool = False,
) -> List[Finding]:
    """Run every registered check against `workflow` and return findings.

    Args:
        workflow: A workflow JSON dict (as returned by N8nApiClient.get_workflow).
        api: An N8nApiClient instance.
        node_name_filter: If set, only return findings for the node with this name.
        strict: If True, promote `severity="warn"` findings to `severity="fail"`.

    Returns:
        List of Finding objects.
    """
    global _CACHE
    _CACHE = _SchemaCache(api)
    try:
        all_findings: List[Finding] = []
        for check in CHECK_REGISTRY:
            results = check.run(workflow, api)
            for f in results:
                if node_name_filter and f.node != node_name_filter:
                    continue
                if strict and f.severity == "warn":
                    f = Finding(
                        node=f.node, node_id=f.node_id, check=f.check,
                        severity="fail", message=f.message,
                    )
                all_findings.append(f)
        return all_findings
    finally:
        _CACHE = None


def has_failures(findings: List[Finding]) -> bool:
    return any(f.severity == "fail" for f in findings)
