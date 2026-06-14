"""Local-network Logitech Harmony client."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional

from aioharmony.const import DEFAULT_DISCOVER_STRING, SendCommandDevice
from aioharmony.exceptions import HarmonyException, TimeOut
from aioharmony.harmonyapi import HarmonyAPI
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError
from zeroconf import ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from .config import get_config

HARMONY_SERVICE_TYPE = DEFAULT_DISCOVER_STRING
VALID_PROTOCOLS = {"WEBSOCKETS", "XMPP"}
HARMONY_PORT_PROTOCOLS = {
    8088: "WEBSOCKETS",
    5222: "XMPP",
}

activity = get_activity_logger("harmony")


def _decode_properties(properties: dict[Any, Any]) -> dict[str, str]:
    decoded = {}
    for key, value in properties.items():
        text_key = key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key)
        text_value = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
        decoded[text_key] = text_value
    return decoded


def _service_record(type_: str, name: str, info: ServiceInfo) -> dict:
    addresses = list(info.parsed_addresses())
    properties = _decode_properties(info.properties or {})
    display_name = properties.get("friendlyName") or name.removesuffix(f".{type_}").rstrip(".")
    remote_id = (
        properties.get("remoteId")
        or properties.get("activeRemoteId")
        or properties.get("hubId")
        or (addresses[0] if addresses else name.rstrip("."))
    )
    return {
        "id": str(remote_id),
        "name": display_name,
        "host": (info.server or "").rstrip("."),
        "ip": addresses[0] if addresses else "",
        "port": info.port,
        "protocol": "WEBSOCKETS",
        "service_type": type_,
        "service_name": name.rstrip("."),
        "properties": properties,
    }


class _HarmonyDiscoveryListener(ServiceListener):
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._record(zc, type_, name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._record(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.records.pop(name, None)

    def _record(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name, timeout=1000)
        if info is None:
            return
        record = _service_record(type_, name, info)
        if record["ip"]:
            self.records[name] = record


def discover_harmony_hubs(timeout: float = 3.0) -> list[dict]:
    """Discover Harmony hubs via Bonjour/mDNS."""
    zc = Zeroconf()
    listener = _HarmonyDiscoveryListener()
    try:
        ServiceBrowser(zc, HARMONY_SERVICE_TYPE, listener=listener)
        time.sleep(max(timeout, 0.1))
        return sorted(listener.records.values(), key=lambda record: (record["name"], record["ip"]))
    finally:
        zc.close()


def _primary_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


def _network_from_cidr_or_local(cidr: Optional[str], local_ipv4_factory: Callable[[], str]) -> ipaddress.IPv4Network:
    network_source = cidr or f"{local_ipv4_factory()}/24"
    try:
        network = ipaddress.ip_network(network_source, strict=False)
    except ValueError as exc:
        raise ClientError(f"Invalid CIDR: {network_source}") from exc
    if network.version != 4:
        raise ClientError("Only IPv4 CIDR ranges are supported")
    return network


def _resolve_name(host: str) -> str:
    try:
        return socket.gethostbyaddr(host)[0]
    except OSError:
        return ""


def _probe_one_port(host: str, port: int, timeout: float, connector: Callable[..., Any]) -> bool:
    sock = None
    try:
        sock = connector((host, port), timeout=timeout)
        return True
    except OSError:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def probe_network_ports(
    cidr: Optional[str] = None,
    ports: Optional[list[int]] = None,
    timeout: float = 0.25,
    workers: int = 96,
    max_hosts: int = 1024,
    connector: Callable[..., Any] = socket.create_connection,
    name_resolver: Callable[[str], str] = _resolve_name,
    local_ipv4_factory: Callable[[], str] = _primary_ipv4,
) -> list[dict]:
    """Probe a local IPv4 range for Harmony-compatible TCP ports."""
    selected_ports = sorted(set(ports or HARMONY_PORT_PROTOCOLS.keys()))
    if timeout <= 0:
        raise ClientError("--timeout must be greater than 0")
    if workers < 1:
        raise ClientError("--workers must be at least 1")
    if max_hosts < 1:
        raise ClientError("--max-hosts must be at least 1")
    if not selected_ports:
        raise ClientError("At least one --port value is required")
    for port in selected_ports:
        if port < 1 or port > 65535:
            raise ClientError(f"Invalid TCP port: {port}")

    network = _network_from_cidr_or_local(cidr, local_ipv4_factory)
    hosts = [str(host) for host in network.hosts()]
    if len(hosts) > max_hosts:
        raise ClientError(f"Refusing to probe {len(hosts)} hosts; increase --max-hosts to continue")

    open_ports_by_host: dict[str, list[int]] = {}
    with ThreadPoolExecutor(max_workers=min(workers, max(len(hosts), 1) * len(selected_ports))) as executor:
        futures = {
            executor.submit(_probe_one_port, host, port, timeout, connector): (host, port)
            for host in hosts
            for port in selected_ports
        }
        for future in as_completed(futures):
            host, port = futures[future]
            if future.result():
                open_ports_by_host.setdefault(host, []).append(port)

    records = []
    for host, open_ports in sorted(open_ports_by_host.items()):
        sorted_ports = sorted(open_ports)
        protocols = [HARMONY_PORT_PROTOCOLS[port] for port in sorted_ports if port in HARMONY_PORT_PROTOCOLS]
        name = name_resolver(host)
        records.append(
            {
                "id": host,
                "name": name or host,
                "host": name,
                "ip": host,
                "open_ports": sorted_ports,
                "protocols": protocols,
                "verified": False,
                "probe_method": "tcp",
            }
        )
    return records


def _normalize_protocol(protocol: Optional[str]) -> Optional[str]:
    if protocol is None:
        return None
    normalized = protocol.upper()
    if normalized not in VALID_PROTOCOLS:
        raise ClientError("Protocol must be WEBSOCKETS or XMPP")
    return normalized


def _matches(value: Optional[str], candidate: str) -> bool:
    return bool(value) and value.lower() == candidate.lower()


def _contains_query(record: dict, query: str) -> bool:
    needle = query.lower()
    return any(needle in str(value).lower() for value in record.values() if not isinstance(value, (dict, list)))


def _looks_like_network_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return "." in value or ":" in value


def _json_action(raw_action: Any) -> dict:
    if isinstance(raw_action, dict):
        return raw_action
    if not raw_action:
        return {}
    try:
        parsed = json.loads(raw_action)
    except (TypeError, ValueError):
        return {"raw": raw_action}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


class HarmonyClient:
    """Client for discovering and controlling local Logitech Harmony hubs."""

    def __init__(
        self,
        config=None,
        api_factory: Callable[..., HarmonyAPI] = HarmonyAPI,
        discovery_factory: Callable[[float], list[dict]] = discover_harmony_hubs,
        port_probe_factory: Callable[..., list[dict]] = probe_network_ports,
    ) -> None:
        self.config = config or get_config()
        self._api_factory = api_factory
        self._discovery_factory = discovery_factory
        self._port_probe_factory = port_probe_factory

    def list_hubs(self, limit: int = 100, timeout: Optional[float] = None) -> list[dict]:
        discovery_timeout = self.config.discovery_timeout if timeout is None else timeout
        activity.info("Discovering Harmony hubs timeout=%s", discovery_timeout)
        hubs = self._discovery_factory(discovery_timeout)
        return hubs[:limit] if limit > 0 else hubs

    def get_hub(self, hub: str, protocol: Optional[str] = None) -> dict:
        return self._run(self._get_hub(hub, protocol))

    def list_activities(
        self,
        hub: Optional[str] = None,
        limit: int = 100,
        protocol: Optional[str] = None,
    ) -> list[dict]:
        rows = self._run(self._list_activities(hub, protocol))
        return rows[:limit] if limit > 0 else rows

    def get_activity(self, activity: str, hub: Optional[str] = None, protocol: Optional[str] = None) -> dict:
        return self._run(self._get_activity(activity, hub, protocol))

    def get_current_activity(self, hub: Optional[str] = None, protocol: Optional[str] = None) -> dict:
        return self._run(self._get_current_activity(hub, protocol))

    def start_activity(self, activity_name_or_id: str, hub: Optional[str] = None, protocol: Optional[str] = None) -> dict:
        return self._run(self._start_activity(activity_name_or_id, hub, protocol))

    def power_off(self, hub: Optional[str] = None, protocol: Optional[str] = None) -> dict:
        return self._run(self._power_off(hub, protocol))

    def sync(self, hub: Optional[str] = None, protocol: Optional[str] = None) -> dict:
        return self._run(self._sync(hub, protocol))

    def get_config(self, hub: Optional[str] = None, protocol: Optional[str] = None) -> dict:
        return self._run(self._get_config(hub, protocol))

    def list_devices(
        self,
        hub: Optional[str] = None,
        limit: int = 100,
        protocol: Optional[str] = None,
    ) -> list[dict]:
        rows = self._run(self._list_devices(hub, protocol))
        return rows[:limit] if limit > 0 else rows

    def get_device(self, device: str, hub: Optional[str] = None, protocol: Optional[str] = None) -> dict:
        return self._run(self._get_device(device, hub, protocol))

    def list_commands(
        self,
        device: str,
        hub: Optional[str] = None,
        limit: int = 100,
        protocol: Optional[str] = None,
    ) -> list[dict]:
        rows = self._run(self._list_commands(device, hub, protocol))
        return rows[:limit] if limit > 0 else rows

    def get_command(
        self,
        device: str,
        command: str,
        hub: Optional[str] = None,
        protocol: Optional[str] = None,
    ) -> dict:
        return self._run(self._get_command(device, command, hub, protocol))

    def send_command(
        self,
        device: str,
        command: str,
        hub: Optional[str] = None,
        protocol: Optional[str] = None,
        repeat: int = 1,
        delay: float = 0.4,
        hold: float = 0.0,
    ) -> dict:
        return self._run(self._send_command(device, command, hub, protocol, repeat, delay, hold))

    def change_channel(self, channel: str, hub: Optional[str] = None, protocol: Optional[str] = None) -> dict:
        return self._run(self._change_channel(channel, hub, protocol))

    def search_hubs(self, query: str, limit: int = 100, timeout: Optional[float] = None) -> list[dict]:
        return [hub for hub in self.list_hubs(limit=0, timeout=timeout) if _contains_query(hub, query)][:limit]

    def probe_hubs(
        self,
        cidr: Optional[str] = None,
        ports: Optional[list[int]] = None,
        timeout: float = 0.25,
        workers: int = 96,
        max_hosts: int = 1024,
        limit: int = 100,
        verify: bool = True,
    ) -> list[dict]:
        records = self._port_probe_factory(
            cidr=cidr,
            ports=ports,
            timeout=timeout,
            workers=workers,
            max_hosts=max_hosts,
        )
        if verify:
            records = [self._verify_probe_record(record) for record in records]
        return records[:limit] if limit > 0 else records

    def search_activities(self, query: str, hub: Optional[str] = None, limit: int = 100) -> list[dict]:
        return [row for row in self.list_activities(hub=hub, limit=0) if _contains_query(row, query)][:limit]

    def search_devices(self, query: str, hub: Optional[str] = None, limit: int = 100) -> list[dict]:
        return [row for row in self.list_devices(hub=hub, limit=0) if _contains_query(row, query)][:limit]

    def _run(self, coroutine):
        try:
            return asyncio.run(coroutine)
        except ClientError:
            raise
        except (HarmonyException, OSError, socket.error) as exc:
            raise ClientError(str(exc)) from exc

    def _verify_probe_record(self, record: dict) -> dict:
        protocols = record.get("protocols") or ["WEBSOCKETS"]
        for protocol in protocols:
            try:
                status = self.get_hub(record["ip"], protocol=protocol)
            except ClientError as exc:
                record = {**record, "verified": False, "error": str(exc)}
                continue
            return {
                **record,
                **status,
                "open_ports": record.get("open_ports", []),
                "protocols": record.get("protocols", []),
                "host": record.get("host", ""),
                "verified": True,
                "probe_method": record.get("probe_method", "tcp"),
            }
        return record

    async def _with_hub(self, hub: Optional[str], protocol: Optional[str], action):
        ip_address = self._resolve_hub(hub)
        selected_protocol = _normalize_protocol(protocol or self.config.default_protocol)
        api = self._api_factory(ip_address=ip_address, protocol=selected_protocol)
        activity.info("Connecting to Harmony hub %s protocol=%s", ip_address, selected_protocol)
        try:
            connected = await api.connect()
            if not connected:
                raise ClientError(f"Failed to connect to Harmony hub {ip_address}")
            return await action(api)
        except TimeOut as exc:
            raise ClientError(f"Harmony hub {ip_address} timed out") from exc
        finally:
            try:
                await api.close()
            except Exception as exc:  # pragma: no cover - best-effort close
                activity.warning("Failed closing Harmony hub %s: %s", ip_address, exc)

    def _resolve_hub(self, hub: Optional[str]) -> str:
        candidate = hub or self.config.default_hub
        if candidate:
            if _looks_like_network_address(candidate):
                return candidate
            matched = self._find_discovered_hub(candidate)
            return matched["ip"] if matched else candidate

        hubs = self.list_hubs(limit=0)
        if not hubs:
            raise ClientError(
                "No Harmony hubs discovered. Pass --hub IP_ADDRESS or set HARMONY_HUB "
                f"in {self.config.config_env_file_path}."
            )
        if len(hubs) > 1:
            names = ", ".join(f"{record['name']} ({record['ip']})" for record in hubs)
            raise ClientError(f"Multiple Harmony hubs discovered; pass --hub. Found: {names}")
        return hubs[0]["ip"]

    def _find_discovered_hub(self, hub: str) -> Optional[dict]:
        for record in self.list_hubs(limit=0):
            if any(
                _matches(record.get(field), hub)
                for field in ("id", "name", "host", "ip", "service_name")
            ):
                return record
        return None

    async def _get_hub(self, hub: str, protocol: Optional[str]):
        return await self._with_hub(hub, protocol, self._hub_status)

    async def _list_activities(self, hub: Optional[str], protocol: Optional[str]):
        return await self._with_hub(hub, protocol, self._activity_records)

    async def _get_activity(self, activity_name_or_id: str, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            return self._find_activity(api, activity_name_or_id)

        return await self._with_hub(hub, protocol, action)

    async def _get_current_activity(self, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            activity_id, activity_name = api.current_activity
            return {
                "hub_id": str(api.hub_id or ""),
                "hub_name": api.name or "",
                "activity_id": str(activity_id),
                "activity_name": activity_name or "",
                "status": "off" if str(activity_id) == "-1" else "active",
            }

        return await self._with_hub(hub, protocol, action)

    async def _start_activity(self, activity_name_or_id: str, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            record = self._find_activity(api, activity_name_or_id)
            success, message = await api.start_activity(record["id"])
            if not success:
                raise ClientError(f"Failed to start activity {activity_name_or_id}: {message}")
            return {
                "hub_id": str(api.hub_id or ""),
                "hub_name": api.name or "",
                "activity_id": record["id"],
                "activity_name": record["name"],
                "success": True,
                "message": message or "started",
            }

        return await self._with_hub(hub, protocol, action)

    async def _power_off(self, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            success = await api.power_off()
            if not success:
                raise ClientError("Failed to power off Harmony hub")
            return {
                "hub_id": str(api.hub_id or ""),
                "hub_name": api.name or "",
                "success": True,
                "message": "powered off",
            }

        return await self._with_hub(hub, protocol, action)

    async def _sync(self, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            success = await api.sync()
            if not success:
                raise ClientError("Failed to sync Harmony hub")
            return {
                "hub_id": str(api.hub_id or ""),
                "hub_name": api.name or "",
                "success": True,
                "message": "sync complete",
            }

        return await self._with_hub(hub, protocol, action)

    async def _get_config(self, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            status = await self._hub_status(api)
            return {"hub": status, "configuration": api.config}

        return await self._with_hub(hub, protocol, action)

    async def _list_devices(self, hub: Optional[str], protocol: Optional[str]):
        return await self._with_hub(hub, protocol, self._device_records)

    async def _get_device(self, device_name_or_id: str, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            return self._find_device(api, device_name_or_id)

        return await self._with_hub(hub, protocol, action)

    async def _list_commands(self, device_name_or_id: str, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            device = self._find_device(api, device_name_or_id)
            return self._command_records(device)

        return await self._with_hub(hub, protocol, action)

    async def _get_command(self, device_name_or_id: str, command_name_or_id: str, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            device = self._find_device(api, device_name_or_id)
            for record in self._command_records(device):
                if any(_matches(record.get(field), command_name_or_id) for field in ("id", "name", "command")):
                    return record
            raise ClientError(f"Command not found: {command_name_or_id}")

        return await self._with_hub(hub, protocol, action)

    async def _send_command(
        self,
        device_name_or_id: str,
        command: str,
        hub: Optional[str],
        protocol: Optional[str],
        repeat: int,
        delay: float,
        hold: float,
    ):
        async def action(api):
            if repeat < 1:
                raise ClientError("--repeat must be at least 1")
            device = self._find_device(api, device_name_or_id)
            command_record = self._find_command(device, command)
            commands: list[Any] = []
            for index in range(repeat):
                commands.append(
                    SendCommandDevice(
                        device=int(device["id"]),
                        command=command_record["command"],
                        delay=hold,
                    )
                )
                if delay > 0 and index < repeat - 1:
                    commands.append(delay)
            errors = await api.send_commands(commands)
            if errors:
                messages = "; ".join(f"{err.command.command}: {err.msg}" for err in errors)
                raise ClientError(f"Failed to send command: {messages}")
            return {
                "hub_id": str(api.hub_id or ""),
                "hub_name": api.name or "",
                "device_id": device["id"],
                "device_name": device["name"],
                "command": command_record["command"],
                "repeat": repeat,
                "success": True,
            }

        return await self._with_hub(hub, protocol, action)

    async def _change_channel(self, channel: str, hub: Optional[str], protocol: Optional[str]):
        async def action(api):
            if not channel.isdigit():
                raise ClientError("Channel must be numeric")
            success = await api.change_channel(int(channel))
            if not success:
                raise ClientError(f"Failed to change channel to {channel}")
            return {
                "hub_id": str(api.hub_id or ""),
                "hub_name": api.name or "",
                "channel": channel,
                "success": True,
            }

        return await self._with_hub(hub, protocol, action)

    async def _hub_status(self, api) -> dict:
        activity_id, activity_name = api.current_activity
        config = api.config or {}
        return {
            "id": str(api.hub_id or ""),
            "name": api.name or "",
            "ip": api.ip_address,
            "protocol": api.protocol or "",
            "firmware_version": api.fw_version or "",
            "account_id": api.account_id or "",
            "email": api.email or "",
            "current_activity_id": str(activity_id),
            "current_activity_name": activity_name or "",
            "activity_count": len(config.get("activity", [])),
            "device_count": len(config.get("device", [])),
        }

    async def _activity_records(self, api) -> list[dict]:
        return self._activity_records_from_api(api)

    def _activity_records_from_api(self, api) -> list[dict]:
        current_id, _ = api.current_activity
        current_id = str(current_id)
        records = []
        for raw in api.config.get("activity", []):
            record = dict(raw)
            record["id"] = str(raw.get("id", ""))
            record["name"] = raw.get("label") or raw.get("name") or record["id"]
            record["label"] = raw.get("label") or record["name"]
            record["status"] = "current" if record["id"] == current_id else "available"
            records.append(record)
        return sorted(records, key=lambda record: record["name"].lower())

    async def _device_records(self, api) -> list[dict]:
        return self._device_records_from_api(api)

    def _device_records_from_api(self, api) -> list[dict]:
        records = []
        for raw in api.config.get("device", []):
            record = dict(raw)
            record["id"] = str(raw.get("id", ""))
            record["name"] = raw.get("label") or raw.get("name") or record["id"]
            record["label"] = raw.get("label") or record["name"]
            record["manufacturer"] = raw.get("manufacturer") or raw.get("manufacturerName") or ""
            record["model"] = raw.get("model") or raw.get("modelNumber") or ""
            record["type"] = raw.get("deviceTypeDisplayName") or raw.get("type") or ""
            record["command_count"] = len(self._command_records(record))
            records.append(record)
        return sorted(records, key=lambda record: record["name"].lower())

    def _command_records(self, device: dict) -> list[dict]:
        records = []
        for group in device.get("controlGroup", []) or []:
            group_name = group.get("name") or group.get("label") or ""
            for function in group.get("function", []) or []:
                action_data = _json_action(function.get("action"))
                command = action_data.get("command") or function.get("name") or function.get("label")
                if not command:
                    continue
                name = function.get("label") or function.get("name") or command
                records.append(
                    {
                        "id": f"{device['id']}:{command}",
                        "name": name,
                        "command": command,
                        "device_id": device["id"],
                        "device_name": device["name"],
                        "group": group_name,
                        "action": action_data,
                    }
                )
        return sorted(records, key=lambda record: (record["group"].lower(), record["name"].lower()))

    def _find_activity(self, api, activity_name_or_id: str) -> dict:
        for record in self._activity_records_from_api(api):
            if any(_matches(record.get(field), activity_name_or_id) for field in ("id", "name", "label")):
                return record
        raise ClientError(f"Activity not found: {activity_name_or_id}")

    def _find_device(self, api, device_name_or_id: str) -> dict:
        for record in self._device_records_from_api(api):
            if any(_matches(record.get(field), device_name_or_id) for field in ("id", "name", "label")):
                return record
        raise ClientError(f"Device not found: {device_name_or_id}")

    def _find_command(self, device: dict, command_name_or_id: str) -> dict:
        for record in self._command_records(device):
            if any(_matches(record.get(field), command_name_or_id) for field in ("id", "name", "command")):
                return record
        raise ClientError(f"Command not found: {command_name_or_id}")


_client: Optional[HarmonyClient] = None


def get_client() -> HarmonyClient:
    """Get or create the global Harmony client instance."""
    global _client
    if _client is None:
        _client = HarmonyClient()
    return _client
