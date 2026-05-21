"""Ring client — thin wrapper around the ring-doorbell async SDK.

Architecture mirrors monarch_cli/client.py: a synchronous client that wraps
async SDK methods with asyncio.run(). All ring-doorbell objects are async,
so every public method here calls into ``_run_async``.

Token persistence:
    The Auth(...) constructor takes a ``token_updated_callback`` that fires
    every time the SDK refreshes the OAuth tokens. We wire that callback to
    ``Config.save_token`` so the cached token rotates transparently.
"""
import asyncio
from pathlib import Path
from typing import Callable, List, Optional

from ring_doorbell import (
    Auth,
    AuthenticationError,
    Requires2FAError,
    Ring,
)

from cli_tools_shared.exceptions import ClientError

from .config import Config, get_config
from .models import (
    Device,
    DeviceFamily,
    DeviceHealth,
    DownloadResult,
    Event,
    EventKind,
    LightsState,
    MotionState,
    SirenState,
    SnapshotResult,
    VolumeState,
    create_device,
)


# Map ring-doorbell .family attribute strings to our DeviceFamily enum.
# ring-doorbell uses these exact strings; do not invent new ones.
_FAMILY_MAP = {
    "doorbots": DeviceFamily.DOORBOTS,
    "authorized_doorbots": DeviceFamily.AUTHORIZED_DOORBOTS,
    "stickup_cams": DeviceFamily.STICKUP_CAMS,
    "chimes": DeviceFamily.CHIMES,
    "other": DeviceFamily.OTHER,
}


def _resolve_family(value: str) -> DeviceFamily:
    """Translate a ring-doorbell ``family`` string into the DeviceFamily enum.

    Fails loudly if the SDK returns a family we don't recognise — that's a
    sign the SDK added a new family and our models need updating.
    """
    if value not in _FAMILY_MAP:
        raise ClientError(
            f"Unknown Ring device family '{value}'. Update DeviceFamily in models/item.py."
        )
    return _FAMILY_MAP[value]


class RingClient:
    """Synchronous wrapper around the ring-doorbell Ring + Auth pair.

    Each public method opens (lazily) an event loop, performs the async
    operation against Ring, and closes the underlying aiohttp session
    cleanly.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self._auth: Optional[Auth] = None
        self._ring: Optional[Ring] = None

    # ----- async lifecycle -----

    def _run_async(self, coro):
        return asyncio.run(coro)

    def _token_updated(self, token: dict) -> None:
        """Callback fired by ring-doorbell whenever the OAuth token rotates."""
        self.config.save_token(token)

    def _build_auth(self, token: Optional[dict] = None) -> Auth:
        return Auth(
            self.config.USER_AGENT,
            token,
            self._token_updated,
        )

    async def _ensure_session(self) -> Ring:
        """Build a Ring object from the cached token, refreshing as needed.

        Returns a fully-populated Ring with devices loaded. Raises
        ClientError when no cached token is present — that means the user
        has not completed ``ring auth login``.
        """
        token = self.config.load_token()
        if token is None:
            raise ClientError(
                "Not authenticated. Run 'ring auth login' to authenticate."
            )

        auth = self._build_auth(token)
        try:
            ring = Ring(auth)
            await ring.async_create_session()
            await ring.async_update_data()
        except AuthenticationError as exc:
            await auth.async_close()
            raise ClientError(
                f"Stored Ring token is no longer valid: {exc}. Run 'ring auth login --force'."
            )
        except Exception:
            await auth.async_close()
            raise

        self._auth = auth
        self._ring = ring
        return ring

    async def _close(self) -> None:
        if self._auth is not None:
            await self._auth.async_close()
            self._auth = None
            self._ring = None

    # ----- auth -----

    def login(
        self,
        username: str,
        password: str,
        otp_callback: Callable[[], str],
    ) -> dict:
        """Perform initial username/password login, prompting for 2FA via callback.

        ``otp_callback`` is invoked only when Ring requires 2FA (Requires2FAError).
        On success the new token dict is persisted to the profile data dir.
        """
        async def _login():
            auth = self._build_auth(None)
            try:
                try:
                    token = await auth.async_fetch_token(username, password)
                except Requires2FAError:
                    code = otp_callback()
                    if not code or not str(code).strip():
                        raise ClientError("2FA code is required but none was provided.")
                    token = await auth.async_fetch_token(username, password, str(code).strip())
                except AuthenticationError as exc:
                    raise ClientError(f"Ring login failed: {exc}")
                # async_fetch_token already triggers token_updated; persist defensively
                self.config.save_token(token)
                return {"success": True, "message": "Logged in to Ring"}
            finally:
                await auth.async_close()

        return self._run_async(_login())

    # ----- devices -----

    def list_devices(self) -> List[Device]:
        """Return every device on the account across all families."""
        async def _list():
            ring = await self._ensure_session()
            try:
                results: List[Device] = []
                for dev in ring.devices().all_devices:
                    family = _resolve_family(dev.family)
                    results.append(
                        Device(
                            id=int(dev.id),
                            name=dev.name,
                            family=family,
                            model=dev.model,
                            kind=getattr(dev, "kind", None),
                            location_id=getattr(dev, "location_id", None),
                            timezone=getattr(dev, "timezone", None),
                            address=getattr(dev, "address", None),
                        )
                    )
                return results
            finally:
                await self._close()

        return self._run_async(_list())

    def get_device(self, identifier: str) -> Device:
        """Look a device up by name OR numeric API id."""
        async def _get():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier)
                await dev.async_update_health_data()
                family = _resolve_family(dev.family)
                return Device(
                    id=int(dev.id),
                    name=dev.name,
                    family=family,
                    model=dev.model,
                    kind=getattr(dev, "kind", None),
                    location_id=getattr(dev, "location_id", None),
                    timezone=getattr(dev, "timezone", None),
                    address=getattr(dev, "address", None),
                    battery_life=getattr(dev, "battery_life", None),
                    wifi_name=getattr(dev, "wifi_name", None),
                    wifi_signal_strength=getattr(dev, "wifi_signal_strength", None),
                    connection_status=getattr(dev, "connection_status", None),
                    motion_detection=getattr(dev, "motion_detection", None) if family != DeviceFamily.CHIMES else None,
                    lights=getattr(dev, "lights", None) if family == DeviceFamily.STICKUP_CAMS else None,
                    siren=getattr(dev, "siren", None) if family == DeviceFamily.STICKUP_CAMS else None,
                    volume=getattr(dev, "volume", None),
                    subscribed=getattr(dev, "subscribed", None),
                    subscribed_motion=getattr(dev, "subscribed_motion", None),
                    has_subscription=getattr(dev, "has_subscription", None),
                )
            finally:
                await self._close()

        return self._run_async(_get())

    def get_device_health(self, identifier: str) -> DeviceHealth:
        async def _health():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier)
                await dev.async_update_health_data()
                return DeviceHealth(
                    id=int(dev.id),
                    name=dev.name,
                    family=_resolve_family(dev.family),
                    battery_life=getattr(dev, "battery_life", None),
                    wifi_name=getattr(dev, "wifi_name", None),
                    wifi_signal_strength=getattr(dev, "wifi_signal_strength", None),
                    connection_status=getattr(dev, "connection_status", None),
                )
            finally:
                await self._close()

        return self._run_async(_health())

    # ----- events / history -----

    def list_events(
        self,
        identifier: Optional[str] = None,
        limit: int = 25,
        kind: Optional[EventKind] = None,
    ) -> List[Event]:
        """Return recent events (dings + motion) across one or all video devices."""
        async def _hist():
            ring = await self._ensure_session()
            try:
                target_devices = []
                if identifier is not None:
                    target_devices.append(_find_device(ring, identifier, video_only=True))
                else:
                    target_devices.extend(ring.video_devices())

                results: List[Event] = []
                for dev in target_devices:
                    kind_arg = kind.value if kind is not None else None
                    history = await dev.async_history(limit=limit, kind=kind_arg)
                    for entry in history:
                        results.append(
                            Event(
                                id=str(entry["id"]),
                                device_id=int(dev.id),
                                device_name=dev.name,
                                kind=EventKind(entry["kind"]),
                                created_at=str(entry["created_at"]),
                                answered=entry.get("answered"),
                                recording_is_ready=entry.get("recording_is_ready"),
                                duration=entry.get("duration"),
                                cv_properties=entry.get("cv_properties"),
                            )
                        )
                return results
            finally:
                await self._close()

        return self._run_async(_hist())

    # ----- recordings -----

    def download_event(
        self,
        identifier: str,
        event_id: str,
        output_dir: Optional[Path] = None,
    ) -> DownloadResult:
        """Download the recording for a specific event id from the named device."""
        return self._run_async(
            self._download_event_async(identifier, event_id, output_dir)
        )

    def download_recent(
        self,
        identifier: str,
        count: int,
        kind: Optional[EventKind] = None,
        output_dir: Optional[Path] = None,
    ) -> List[DownloadResult]:
        """Download the most recent ``count`` recordings from a device."""
        async def _recent():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier, video_only=True)
                kind_arg = kind.value if kind is not None else None
                history = await dev.async_history(limit=count, kind=kind_arg)
                results: List[DownloadResult] = []
                for entry in history:
                    result = await self._download_one(dev, entry, output_dir)
                    results.append(result)
                return results
            finally:
                await self._close()

        return self._run_async(_recent())

    async def _download_event_async(
        self,
        identifier: str,
        event_id: str,
        output_dir: Optional[Path],
    ) -> DownloadResult:
        ring = await self._ensure_session()
        try:
            dev = _find_device(ring, identifier, video_only=True)
            history = await dev.async_history(limit=200)
            matches = [h for h in history if str(h["id"]) == str(event_id)]
            if not matches:
                raise ClientError(
                    f"Event id '{event_id}' not found in the last 200 events for device '{dev.name}'."
                )
            return await self._download_one(dev, matches[0], output_dir)
        finally:
            await self._close()

    async def _download_one(
        self,
        dev,
        entry: dict,
        output_dir: Optional[Path],
    ) -> DownloadResult:
        target_dir = output_dir or self.config.download_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        kind = EventKind(entry["kind"])
        filename = f"{dev.name.replace(' ', '_')}_{entry['created_at']}_{entry['id']}.mp4"
        target_path = target_dir / filename
        await dev.async_recording_download(
            entry["id"],
            filename=str(target_path),
            override=True,
        )
        size = target_path.stat().st_size if target_path.exists() else 0
        return DownloadResult(
            event_id=str(entry["id"]),
            device_id=int(dev.id),
            device_name=dev.name,
            kind=kind,
            created_at=str(entry["created_at"]),
            path=str(target_path),
            size_bytes=size,
        )

    # ----- snapshots -----

    def get_snapshot(
        self,
        identifier: str,
        output_path: Optional[Path] = None,
    ) -> SnapshotResult:
        """Capture a fresh JPEG from a doorbell or camera and save it locally."""
        async def _snap():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier, video_only=True)
                jpeg = await dev.async_get_snapshot()
                if not jpeg:
                    raise ClientError(
                        f"Ring returned no snapshot bytes for device '{dev.name}'."
                    )
                target_dir = (output_path or self.config.download_dir).parent if output_path else self.config.download_dir
                if output_path is None:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target_path = target_dir / f"{dev.name.replace(' ', '_')}_snapshot.jpg"
                else:
                    target_path = output_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(jpeg)
                return SnapshotResult(
                    device_id=int(dev.id),
                    device_name=dev.name,
                    family=_resolve_family(dev.family),
                    path=str(target_path),
                    size_bytes=target_path.stat().st_size,
                )
            finally:
                await self._close()

        return self._run_async(_snap())

    # ----- motion detection -----

    def set_motion_detection(self, identifier: str, enabled: bool) -> MotionState:
        async def _motion():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier, video_only=True)
                await dev.async_set_motion_detection(enabled)
                return MotionState(
                    device_id=int(dev.id),
                    device_name=dev.name,
                    enabled=bool(enabled),
                )
            finally:
                await self._close()

        return self._run_async(_motion())

    def get_motion_detection(self, identifier: str) -> MotionState:
        async def _motion():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier, video_only=True)
                return MotionState(
                    device_id=int(dev.id),
                    device_name=dev.name,
                    enabled=bool(getattr(dev, "motion_detection", False)),
                )
            finally:
                await self._close()

        return self._run_async(_motion())

    # ----- lights / siren -----

    def set_lights(self, identifier: str, state: str) -> LightsState:
        if state not in ("on", "off"):
            raise ClientError(f"Invalid lights state '{state}'. Use 'on' or 'off'.")

        async def _lights():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier)
                if dev.family != "stickup_cams":
                    raise ClientError(
                        f"Device '{dev.name}' (family={dev.family}) does not support lights control."
                    )
                await dev.async_set_lights(state)
                return LightsState(
                    device_id=int(dev.id),
                    device_name=dev.name,
                    state=state,
                )
            finally:
                await self._close()

        return self._run_async(_lights())

    def set_siren(self, identifier: str, duration: int) -> SirenState:
        async def _siren():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier)
                if dev.family != "stickup_cams":
                    raise ClientError(
                        f"Device '{dev.name}' (family={dev.family}) does not support siren control."
                    )
                await dev.async_set_siren(duration)
                return SirenState(
                    device_id=int(dev.id),
                    device_name=dev.name,
                    remaining_seconds=duration,
                )
            finally:
                await self._close()

        return self._run_async(_siren())

    # ----- chime test -----

    def chime_test(self, identifier: str, kind: str) -> dict:
        if kind not in ("ding", "motion"):
            raise ClientError(f"Invalid chime kind '{kind}'. Use 'ding' or 'motion'.")

        async def _test():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier)
                if dev.family != "chimes":
                    raise ClientError(
                        f"Device '{dev.name}' (family={dev.family}) is not a chime."
                    )
                await dev.async_test_sound(kind=kind)
                return {"device_id": int(dev.id), "device_name": dev.name, "kind": kind, "played": True}
            finally:
                await self._close()

        return self._run_async(_test())

    # ----- volume -----

    def set_volume(self, identifier: str, value: int) -> VolumeState:
        async def _vol():
            ring = await self._ensure_session()
            try:
                dev = _find_device(ring, identifier)
                await dev.async_set_volume(value)
                return VolumeState(
                    device_id=int(dev.id),
                    device_name=dev.name,
                    volume=value,
                )
            finally:
                await self._close()

        return self._run_async(_vol())


def _find_device(ring: Ring, identifier: str, video_only: bool = False):
    """Resolve a device by name or numeric id. Raises ClientError on miss.

    ``video_only`` restricts the search to doorbells/cameras (devices that
    have history and recording_download endpoints).
    """
    pool = ring.video_devices() if video_only else ring.get_device_list()

    # Try numeric id first
    try:
        wanted_id = int(identifier)
        for dev in pool:
            if int(dev.id) == wanted_id:
                return dev
    except (TypeError, ValueError):
        pass

    # Fall back to name match (case-insensitive exact match)
    for dev in pool:
        if dev.name.lower() == identifier.lower():
            return dev

    if video_only:
        raise ClientError(
            f"No video device matches '{identifier}'. Use 'ring devices list --family doorbots' to see options."
        )
    raise ClientError(
        f"No device matches '{identifier}'. Use 'ring devices list' to see available devices."
    )


_client: Optional[RingClient] = None


def get_client() -> RingClient:
    global _client
    if _client is None:
        _client = RingClient()
    return _client
