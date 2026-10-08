"""Discover every RPC from the pinned official generated SDK."""
import importlib
import inspect
import pkgutil
import re
import typing
from importlib.metadata import version as package_version
from functools import lru_cache

import proto
from google.protobuf import json_format, empty_pb2
from google.api_core.operation import Operation as OperationFuture
from google.longrunning import operations_pb2
from google.protobuf import message_factory
from google.protobuf.message import Message
from cli_tools_shared.exceptions import ClientError

DEFAULT_API_VERSION = "v25"
SDK_VERSION = package_version("google-ads")


def api_versions():
    import google.ads.googleads as package
    return sorted(m.name for m in pkgutil.iter_modules(package.__path__) if re.fullmatch(r"v\d+", m.name))


def protobuf_class(cls):
    if cls is OperationFuture:
        return operations_pb2.Operation
    if cls is type(None):
        return empty_pb2.Empty
    return cls.pb() if issubclass(cls, proto.Message) else cls


def to_dict(value):
    if value is None:
        return {}
    if isinstance(value, OperationFuture):
        value = value.operation
    message = type(value).pb(value) if isinstance(value, proto.Message) else value
    return json_format.MessageToDict(message, preserving_proto_field_name=True)


@lru_cache(maxsize=None)
def catalog(version=DEFAULT_API_VERSION):
    if version not in api_versions():
        raise ClientError(f"Unsupported API version {version!r}; available: {', '.join(api_versions())}")
    package = importlib.import_module(f"google.ads.googleads.{version}.services.services")
    result = {}
    for module in pkgutil.iter_modules(package.__path__):
        service = importlib.import_module(f"{package.__name__}.{module.name}")
        for exported in service.__all__:
            if not exported.endswith("Client") or exported.endswith("AsyncClient"):
                continue
            cls = getattr(service, exported)
            methods = {}
            for name, function in inspect.getmembers(cls, inspect.isfunction):
                if "request" not in inspect.signature(function).parameters:
                    continue
                hints = typing.get_type_hints(function)
                candidates = typing.get_args(hints["request"]) or (hints["request"],)
                request = next((candidate for candidate in candidates if inspect.isclass(candidate) and issubclass(candidate, (proto.Message, Message))), None)
                if request is None:
                    raise ClientError(f"SDK request descriptor missing: {exported}.{name}")
                response = hints["return"]
                stream = typing.get_origin(response) is not None
                paged = inspect.isclass(response) and ".pagers" in response.__module__
                if stream:
                    response = typing.get_args(response)[0]
                elif paged:
                    response = typing.get_type_hints(response.__init__)["response"]
                methods[name] = {"request_class": request, "response_class": response, "stream": stream,
                                 "paged": paged, "read_only": name.startswith(("get_", "list_", "search"))}
            result[exported.removesuffix("Client")] = {"client_class": cls, "methods": methods}
    operation_methods = {}
    for rpc in operations_pb2.DESCRIPTOR.services_by_name["Operations"].methods:
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", rpc.name).lower()
        if name not in {"get_operation", "list_operations", "cancel_operation", "delete_operation"}:
            continue  # The pinned official operations client exposes these four methods.
        operation_methods[name] = {"request_class": message_factory.GetMessageClass(rpc.input_type),
                                   "response_class": message_factory.GetMessageClass(rpc.output_type),
                                   "stream": False, "paged": name == "list_operations",
                                   "read_only": name.startswith(("get_", "list_")), "operations": True}
    result["OperationsService"] = {"client_class": None, "methods": operation_methods}
    return result


def method_info(service, method, version=DEFAULT_API_VERSION):
    services = catalog(version)
    if service not in services:
        raise ClientError(f"Unknown service {service!r}; run 'google-ads api services'.")
    methods = services[service]["methods"]
    if method not in methods:
        raise ClientError(f"Unknown method {service}.{method}; available: {', '.join(methods)}")
    return methods[method]


def public_method(service, method, info):
    return {"service": service, "method": method,
            "request_type": protobuf_class(info["request_class"]).DESCRIPTOR.full_name,
            "response_type": protobuf_class(info["response_class"]).DESCRIPTOR.full_name,
            "server_streaming": info["stream"], "paginated": info["paged"], "read_only": info["read_only"],
            "validate_only_supported": "validate_only" in protobuf_class(info["request_class"]).DESCRIPTOR.fields_by_name}


def coverage(version=DEFAULT_API_VERSION):
    services = catalog(version)
    records = [public_method(service, name, info) for service, entry in services.items() for name, info in entry["methods"].items()]
    return {"sdk_version": SDK_VERSION, "api_version": version, "service_count": len(services),
            "rpc_count": len(records), "rpcs": records}


def request_message(service, method, body, version=DEFAULT_API_VERSION):
    if not isinstance(body, dict):
        raise ClientError("Request JSON must be an object.")
    cls = method_info(service, method, version)["request_class"]
    try:
        message = json_format.ParseDict(body, protobuf_class(cls)(), ignore_unknown_fields=False)
        return cls.wrap(message) if issubclass(cls, proto.Message) else message
    except (ValueError, TypeError, json_format.ParseError) as exc:
        raise ClientError(f"Invalid request for {service}.{method}: {exc}") from exc


def message_schema(service, method, version=DEFAULT_API_VERSION):
    info = method_info(service, method, version)
    pending = [protobuf_class(info[key]).DESCRIPTOR for key in ("request_class", "response_class")]
    definitions = {}
    while pending:
        descriptor = pending.pop()
        if descriptor.full_name in definitions:
            continue
        fields = []
        definitions[descriptor.full_name] = {"fields": fields, "oneofs": [oneof.name for oneof in descriptor.oneofs]}
        for field in descriptor.fields:
            record = {"name": field.name, "json_name": field.json_name, "number": field.number,
                      "type": field.type, "repeated": field.is_repeated,
                      "oneof": field.containing_oneof.name if field.containing_oneof else None}
            if field.message_type:
                record["message_type"] = field.message_type.full_name
                pending.append(field.message_type)
            if field.enum_type:
                record["enum_values"] = {value.name: value.number for value in field.enum_type.values}
            fields.append(record)
    return {**public_method(service, method, info), "messages": definitions}
