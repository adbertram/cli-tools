"""Discover the exact API operations shipped by the pinned Meta SDK."""

import ast
from functools import lru_cache
from importlib import import_module, metadata
from pathlib import Path

import facebook_business.adobjects
from cli_tools_shared.exceptions import ClientError

SDK_VERSION = metadata.version("facebook-business")
API_VERSION = "v26.0"


@lru_cache(maxsize=1)
def catalog() -> dict:
    """Read generated request declarations, excluding non-API helpers."""
    result = {}
    root = Path(facebook_business.adobjects.__file__).parent
    for source in sorted(root.glob("*.py")):
        if source.stem.startswith("abstract"):
            continue
        tree = ast.parse(source.read_text())
        for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            if not any(isinstance(base, ast.Name) and base.id in {"AbstractObject", "AbstractCrudObject"} for base in cls.bases):
                continue
            methods = {}
            for method in (node for node in cls.body if isinstance(node, ast.FunctionDef)):
                requests = [node for node in ast.walk(method) if isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name) and node.func.id == "FacebookRequest"]
                if not requests:
                    continue
                call = requests[0]
                values = {kw.arg: kw.value for kw in call.keywords}
                params = next((node.value for node in method.body if isinstance(node, ast.Assign)
                               and any(isinstance(target, ast.Name) and target.id == "param_types"
                                       for target in node.targets)), None)
                methods[method.name] = {
                    "method": ast.literal_eval(values["method"]),
                    "endpoint": ast.literal_eval(values["endpoint"]),
                    "parameters": ast.literal_eval(params) if params else {},
                    "arguments": [arg.arg for arg in method.args.args if arg.arg != "self"],
                }
            result[cls.name] = {"module": source.stem, "methods": methods}
    return result


def resource_class(name: str):
    """Resolve only a discovered SDK resource, never arbitrary import paths."""
    record = catalog().get(name)
    if record is None:
        raise ClientError(f"Unknown SDK resource '{name}'. Run facebook-ads sdk resources list.")
    return getattr(import_module(f"facebook_business.adobjects.{record['module']}"), name)


def operation(name: str, method: str) -> dict:
    record = catalog().get(name, {}).get("methods", {}).get(method)
    if record is None:
        raise ClientError(f"Unknown API operation '{name}.{method}'. Run facebook-ads sdk methods list {name}.")
    return record


def schema(name: str, method: str | None = None) -> dict:
    cls = resource_class(name)
    obj = cls("0") if method else cls()
    result = {"resource": name, "sdk_version": SDK_VERSION,
              "api_version": API_VERSION, "fields": getattr(obj, "_field_types", {}),
              "methods": catalog()[name]["methods"]}
    if method:
        record = operation(name, method)
        request = getattr(obj, method)(pending=True)
        enums = getattr(request._param_checker, "_enum_data", {})
        result["operation"] = {"name": method, **record,
                               "enums": {key: sorted(value for value in values if isinstance(value, str)
                                                      and not value.startswith("facebook_business"))
                                         for key, values in enums.items()}}
    return result
