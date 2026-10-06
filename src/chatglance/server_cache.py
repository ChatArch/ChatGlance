"""Identity-fenced, transaction-ready last-good server snapshots.

The module only prepares payloads.  Callers must publish ``last_good`` in the
same transaction as the visible server snapshot; no helper here commits it.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import stat
from typing import Any, Iterable, cast


SCHEMA_VERSION = 1
LAST_GOOD_RELATIVE = Path("private/server-last-good.json")
MAX_CACHE_BYTES = 16 * 1024 * 1024
MAX_LEGACY_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_LEGACY_TOTAL_BYTES = 64 * 1024 * 1024
MAX_LEGACY_BACKUPS = 64
MAX_SERVERS = 4096
SERVER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
NUMERIC_BACKUP_RE = re.compile(r"[0-9]+\Z")

_DATA_FIELDS = (
    "alias",
    "display_name",
    "group",
    "connection_kind",
    "ip",
    "hostname",
    "user",
    "kernel",
    "collected_at",
    "last_reboot",
    "uptime_seconds",
    "cpu",
    "memory",
    "gpus",
    "disks",
    "devices",
    "getdevices",
)
_HARDWARE_FIELDS = (
    "hostname",
    "user",
    "kernel",
    "last_reboot",
    "uptime_seconds",
    "cpu",
    "memory",
    "gpus",
    "disks",
    "devices",
    "getdevices",
)


class ServerCacheError(ValueError):
    """A cache or identity could not be handled without weakening fencing."""


@dataclass(frozen=True)
class ServerCachePlan:
    """Prepared visible snapshot and private state for transactional publish."""

    snapshot: dict[str, Any]
    last_good: dict[str, Any]
    changed: bool
    bootstrapped_aliases: tuple[str, ...]


@dataclass(frozen=True)
class _ReviewedIdentity:
    server_id: str
    alias: str
    target: str
    port: str
    user: str
    legacy_identities: tuple[dict[str, str], ...] = ()

    def public(self) -> dict[str, str]:
        return {
            "server_id": self.server_id,
            "alias": self.alias,
            "target": self.target,
            "port": self.port,
            "user": self.user,
        }


def last_good_path(runtime_home: str | Path) -> Path:
    """Return the package-owned private last-good location."""

    return Path(runtime_home).expanduser() / LAST_GOOD_RELATIVE


def dump_last_good(value: dict[str, Any]) -> str:
    """Serialize a prepared last-good document deterministically."""

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ServerCacheError("now must include a timezone")
    return current.astimezone(timezone.utc)


def _timestamp(value: Any, *, now: datetime, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64 or any(char.isspace() for char in value.strip(" ")):
        raise ServerCacheError(f"{field} must be a bounded timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ServerCacheError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ServerCacheError(f"{field} must include a timezone")
    if parsed.astimezone(timezone.utc) > now + timedelta(minutes=5):
        raise ServerCacheError(f"{field} is in the future")
    return value


def _safe_text(value: Any, *, field: str, required: bool = False, limit: int = 4096) -> str:
    if not isinstance(value, str):
        raise ServerCacheError(f"{field} must be text")
    if required and not value.strip():
        raise ServerCacheError(f"{field} is required")
    if len(value) > limit or "\x00" in value or any(ord(char) < 32 and char not in "\t\r\n" for char in value):
        raise ServerCacheError(f"{field} is invalid")
    return value


def _validate_json_value(value: Any, *, depth: int = 0) -> None:
    if depth > 12:
        raise ServerCacheError("server data is too deeply nested")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and (len(value) > 16384 or "\x00" in value):
            raise ServerCacheError("server data contains invalid text")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ServerCacheError("server data contains a non-finite number")
        return
    if isinstance(value, list):
        if len(value) > 8192:
            raise ServerCacheError("server data list is too large")
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 1024:
            raise ServerCacheError("server data object is too large")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise ServerCacheError("server data key is invalid")
            _validate_json_value(item, depth=depth + 1)
        return
    raise ServerCacheError("server data contains a non-JSON value")


def _success_data(row: dict[str, Any], *, now: datetime) -> tuple[dict[str, Any], str]:
    if row.get("status") != "online":
        raise ServerCacheError("last-good source must be online")
    alias = _safe_text(row.get("alias"), field="alias", required=True, limit=256)
    observed_at = _timestamp(row.get("collected_at"), now=now, field=f"{alias}.collected_at")
    if not isinstance(row.get("cpu"), dict) or not isinstance(row.get("memory"), dict):
        raise ServerCacheError(f"{alias} has invalid CPU or memory data")
    for field in ("gpus", "disks", "devices", "getdevices"):
        if not isinstance(row.get(field), list):
            raise ServerCacheError(f"{alias} has invalid {field} data")
    # disks and devices are deliberately required groups even when the valid
    # observation is an empty list.
    for field in ("hostname", "user", "kernel", "last_reboot", "uptime_seconds"):
        _safe_text(row.get(field, ""), field=f"{alias}.{field}", required=field in {"hostname", "user"})
    data = {key: deepcopy(row[key]) for key in _DATA_FIELDS if key in row}
    _validate_json_value(data)
    try:
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ServerCacheError(f"{alias} data is not serializable") from exc
    if len(encoded) > MAX_LEGACY_SNAPSHOT_BYTES:
        raise ServerCacheError(f"{alias} data is too large")
    return data, observed_at


def _inventory(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("inventory", config.get("server_inventory", config))
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ServerCacheError("inventory must be an object")
    return cast(dict[str, Any], value)


def _connection_target(alias: str, item: dict[str, Any]) -> tuple[str, str, str]:
    target = str(item.get("hostname") or item.get("host") or "").strip()
    user = str(item.get("user") or "").strip()
    port = str(item.get("port") or "").strip()
    if not target or not user or not port:
        from .servers import ssh_target

        try:
            resolved = ssh_target(alias, {
                key: str(item[key]).strip()
                for key in ("hostname", "port", "user")
                if item.get(key) is not None and str(item[key]).strip()
            })
        except Exception as exc:
            raise ServerCacheError(f"could not resolve reviewed connection identity for {alias}") from exc
        target = target or str(resolved.get("hostname") or "").strip()
        user = user or str(resolved.get("user") or "").strip()
        port = port or str(resolved.get("port") or "22").strip()
    if not target or len(target) > 255 or any(char.isspace() or ord(char) < 33 for char in target):
        raise ServerCacheError(f"invalid reviewed target for {alias}")
    if not user or len(user) > 256 or any(char.isspace() or ord(char) < 33 for char in user):
        raise ServerCacheError(f"invalid reviewed user for {alias}")
    try:
        number = int(port)
    except ValueError as exc:
        raise ServerCacheError(f"invalid reviewed port for {alias}") from exc
    if not 1 <= number <= 65535:
        raise ServerCacheError(f"invalid reviewed port for {alias}")
    try:
        normalized_target = str(ipaddress.ip_address(target))
    except ValueError:
        normalized_target = target.rstrip(".").lower()
    return normalized_target, str(number), user


def _legacy_identities(item: dict[str, Any], identity: tuple[str, str, str], alias: str) -> tuple[dict[str, str], ...]:
    raw = item.get("legacy_identities", [])
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ServerCacheError(f"legacy identities for {alias} must be a list")
    target, port, user = identity
    del target
    accepted: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("approved") is not True:
            raise ServerCacheError(f"legacy identity for {alias} must be explicitly approved")
        ip = str(entry.get("ip") or "").strip()
        old_user = str(entry.get("user") or "").strip()
        old_port = str(entry.get("port") or "").strip()
        try:
            ip = str(ipaddress.ip_address(ip))
            old_port = str(int(old_port))
        except (ValueError, TypeError) as exc:
            raise ServerCacheError(f"legacy identity for {alias} is invalid") from exc
        if not (1 <= int(old_port) <= 65535) or old_port != port or old_user != user:
            raise ServerCacheError(f"legacy identity for {alias} does not match the reviewed user/port")
        accepted.append({"ip": ip, "port": old_port, "user": old_user})
    return tuple(accepted)


def _reviewed_identities(config: dict[str, Any]) -> dict[str, _ReviewedIdentity]:
    inventory = _inventory(config)
    raw_hosts = inventory.get("hosts", [])
    if raw_hosts is None:
        return {}
    if not isinstance(raw_hosts, list):
        raise ServerCacheError("inventory.hosts must be a list")
    from .servers import aliases_from_inventory_config

    host_items: dict[str, dict[str, Any]] = {}
    for raw in raw_hosts:
        if isinstance(raw, dict):
            alias = str(raw.get("alias") or "").strip()
            if alias and alias not in host_items:
                host_items[alias] = raw
    identities: dict[str, _ReviewedIdentity] = {}
    server_ids: set[str] = set()
    for alias in aliases_from_inventory_config(config):
        raw = host_items.get(alias, {})
        raw_server_id = raw.get("server_id", raw.get("server-id"))
        if not alias:
            continue
        if raw_server_id is not None and (not isinstance(raw_server_id, str) or not SERVER_ID_RE.fullmatch(raw_server_id)):
            continue
        try:
            target = _connection_target(alias, raw)
            legacy = _legacy_identities(raw, target, alias)
        except ServerCacheError:
            # One unreviewable host must not weaken its own fence or prevent
            # independent, valid inventory hosts from retaining last-good.
            continue
        if raw_server_id is None:
            identity_material = json.dumps(
                [alias, target[0], target[2], target[1]],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            raw_server_id = f"derived-{hashlib.sha256(identity_material).hexdigest()}"
        if alias in identities or raw_server_id in server_ids:
            raise ServerCacheError("server aliases and stable server_id values must be unique")
        identities[alias] = _ReviewedIdentity(
            server_id=raw_server_id,
            alias=alias,
            target=target[0],
            port=target[1],
            user=target[2],
            legacy_identities=legacy,
        )
        server_ids.add(raw_server_id)
    return identities


def _safe_cache_path(path: Path) -> None:
    parent = path.parent
    if parent.exists():
        metadata = parent.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ServerCacheError("last-good parent must be a real directory, not a symlink")
    if path.exists() or path.is_symlink():
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ServerCacheError("last-good path must not be a symlink")
        if not stat.S_ISREG(metadata.st_mode):
            raise ServerCacheError("last-good path must be a regular file")


def _empty_cache() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "servers": {}}


def _load_cache(root: Path, *, now: datetime) -> tuple[dict[str, Any], bool]:
    path = last_good_path(root)
    _safe_cache_path(path)
    if not path.exists():
        return _empty_cache(), False
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            return _empty_cache(), False
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("servers"), dict):
            return _empty_cache(), False
        validated: dict[str, Any] = {}
        for server_id, entry in value["servers"].items():
            if not isinstance(server_id, str) or not SERVER_ID_RE.fullmatch(server_id) or not isinstance(entry, dict):
                return _empty_cache(), False
            identity = entry.get("identity")
            data = entry.get("data")
            if not isinstance(identity, dict) or identity.get("server_id") != server_id or not isinstance(data, dict):
                return _empty_cache(), False
            expected_keys = {"server_id", "alias", "target", "port", "user"}
            if set(identity) != expected_keys or not all(isinstance(identity[key], str) and identity[key] for key in expected_keys):
                return _empty_cache(), False
            observed = _timestamp(entry.get("last_success_at"), now=now, field=f"{server_id}.last_success_at")
            clean, clean_observed = _success_data({**data, "status": "online", "collected_at": observed}, now=now)
            if clean_observed != observed:
                return _empty_cache(), False
            restored = {
                "identity": deepcopy(identity),
                "last_success_at": observed,
                "data": clean,
            }
            if isinstance(entry.get("run_id"), str) and len(entry["run_id"]) <= 128:
                restored["run_id"] = entry["run_id"]
            if entry.get("bootstrap") is True:
                restored["bootstrap"] = True
            validated[server_id] = restored
        result = {"schema_version": SCHEMA_VERSION, "servers": validated}
        if isinstance(value.get("updated_at"), str):
            result["updated_at"] = _timestamp(value["updated_at"], now=now, field="updated_at")
        return result, True
    except (OSError, UnicodeError, json.JSONDecodeError, ServerCacheError):
        return _empty_cache(), False


def _read_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_LEGACY_SNAPSHOT_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("servers"), list) or len(value["servers"]) > MAX_SERVERS:
        return None
    return cast(dict[str, Any], value)


def _legacy_snapshots(root: Path) -> Iterable[dict[str, Any]]:
    remaining_bytes = MAX_LEGACY_TOTAL_BYTES

    def bounded_read(path: Path) -> dict[str, Any] | None:
        nonlocal remaining_bytes
        try:
            metadata = path.lstat()
        except OSError:
            return None
        if metadata.st_size > remaining_bytes:
            return None
        remaining_bytes -= metadata.st_size
        return _read_snapshot(path)

    live = root / "data/server-status.json"
    if live.exists() or live.is_symlink():
        value = bounded_read(live)
        if value is not None:
            yield value
    backups = root / "config/backups"
    try:
        candidates = [
            path
            for path in backups.iterdir()
            if path.name.startswith("refresh-") and not path.is_symlink() and path.is_dir()
        ]
    except OSError:
        return
    for backup in sorted(candidates, key=lambda path: path.name, reverse=True)[:MAX_LEGACY_BACKUPS]:
        manifest = backup / "manifest.json"
        try:
            metadata = manifest.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 1024 * 1024:
                continue
            mapping = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        stored = mapping.get("data/server-status.json") if isinstance(mapping, dict) else None
        if not isinstance(stored, str) or not NUMERIC_BACKUP_RE.fullmatch(stored):
            continue
        value = bounded_read(backup / stored)
        if value is not None:
            yield value


def _legacy_matches(row: dict[str, Any], identity: _ReviewedIdentity) -> bool:
    if row.get("alias") != identity.alias or not isinstance(row.get("ip"), str) or not isinstance(row.get("user"), str):
        return False
    if row["user"] != identity.user:
        return False
    try:
        endpoint_ip = str(ipaddress.ip_address(row["ip"]))
    except ValueError:
        return False
    try:
        target_ip = str(ipaddress.ip_address(identity.target))
    except ValueError:
        target_ip = ""
    if target_ip:
        return endpoint_ip == target_ip
    return any(
        item["ip"] == endpoint_ip and item["port"] == identity.port and item["user"] == identity.user
        for item in identity.legacy_identities
    )


def _bootstrap_entry(root: Path, identity: _ReviewedIdentity, *, now: datetime) -> dict[str, Any] | None:
    for snapshot in _legacy_snapshots(root):
        generated_at = snapshot.get("generated_at")
        if generated_at is not None:
            try:
                _timestamp(generated_at, now=now, field="legacy.generated_at")
            except ServerCacheError:
                continue
        matching_alias = [raw for raw in snapshot.get("servers", []) if isinstance(raw, dict) and raw.get("alias") == identity.alias]
        if len(matching_alias) != 1:
            continue
        raw = matching_alias[0]
        if raw.get("status") != "online" or not _legacy_matches(raw, identity):
            continue
        try:
            data, observed_at = _success_data(raw, now=now)
        except ServerCacheError:
            continue
        return {
            "identity": identity.public(),
            "last_success_at": observed_at,
            "data": data,
            "bootstrap": True,
        }
    return None


def _attempted_at(row: dict[str, Any], snapshot: dict[str, Any], *, now: datetime) -> str | None:
    value = row.get("collected_at") or snapshot.get("generated_at")
    if value is None:
        return None
    return _timestamp(value, now=now, field=f"{row.get('alias', 'server')}.last_attempt_at")


def prepare_server_refresh(
    runtime_home: str | Path,
    current: dict[str, Any],
    inventory: dict[str, Any],
    *,
    run_id: str | None = None,
    now: datetime | None = None,
) -> ServerCachePlan:
    """Prepare truthful current rows plus fenced last-good data.

    ``current`` remains authoritative for membership and connectivity state.
    Hardware fields are overlaid only when a stored or manifest-confirmed
    observation has the exact reviewed identity.
    """

    current_time = _now(now)
    if not isinstance(current, dict) or not isinstance(current.get("servers"), list):
        raise ServerCacheError("server snapshot must contain a servers list")
    if len(current["servers"]) > MAX_SERVERS:
        raise ServerCacheError("server snapshot contains too many rows")
    if current.get("generated_at") is not None:
        _timestamp(current["generated_at"], now=current_time, field="generated_at")
    root = Path(runtime_home).expanduser()
    identities = _reviewed_identities(inventory) if current["servers"] else {}
    old_cache, cache_valid = _load_cache(root, now=current_time)
    old_entries = old_cache.get("servers", {}) if cache_valid else {}
    next_entries: dict[str, Any] = {}
    bootstrapped: list[str] = []
    result = deepcopy(current)
    seen_aliases: set[str] = set()
    visible_rows: list[dict[str, Any]] = []

    for raw in result["servers"]:
        if not isinstance(raw, dict):
            raise ServerCacheError("server rows must be objects")
        _validate_json_value(raw)
        alias = _safe_text(raw.get("alias"), field="alias", required=True, limit=256)
        if alias in seen_aliases:
            raise ServerCacheError("server aliases must be unique")
        seen_aliases.add(alias)
        status = raw.get("status")
        if status not in {"online", "unreachable", "error"}:
            raise ServerCacheError(f"invalid current status for {alias}")
        attempted_at = _attempted_at(raw, current, now=current_time)
        if attempted_at is not None:
            raw["last_attempt_at"] = attempted_at
        identity = identities.get(alias)
        entry: dict[str, Any] | None = None
        if identity is not None:
            candidate = old_entries.get(identity.server_id)
            if isinstance(candidate, dict) and candidate.get("identity") == identity.public():
                entry = deepcopy(candidate)
            if status == "online":
                data, observed_at = _success_data(raw, now=current_time)
                entry = {
                    "identity": identity.public(),
                    "last_success_at": observed_at,
                    "data": data,
                }
                if run_id:
                    entry["run_id"] = run_id
            elif entry is None:
                entry = _bootstrap_entry(root, identity, now=current_time)
                if entry is not None:
                    bootstrapped.append(alias)
            if entry is not None:
                next_entries[identity.server_id] = deepcopy(entry)

        if status == "online":
            observed = attempted_at
            if identity is not None and entry is not None:
                observed = entry["last_success_at"]
            raw["data_state"] = "fresh"
            if observed is not None:
                raw["last_observed_at"] = observed
                raw["last_success_at"] = observed
        elif entry is not None:
            for field in _HARDWARE_FIELDS:
                if field in entry["data"]:
                    raw[field] = deepcopy(entry["data"][field])
            raw["data_state"] = "last-good"
            raw["last_observed_at"] = entry["last_success_at"]
            raw["last_success_at"] = entry["last_success_at"]
        else:
            for field in _HARDWARE_FIELDS:
                raw.pop(field, None)
            raw["data_state"] = "unavailable"
            raw.pop("last_observed_at", None)
            raw.pop("last_success_at", None)
        raw.pop("note", None)
        visible_rows.append(raw)

    result["servers"] = visible_rows
    result["count"] = len(visible_rows)
    result["online"] = sum(row.get("status") == "online" for row in visible_rows)
    next_cache: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "servers": next_entries}
    changed = next_entries != old_entries
    if changed:
        next_cache["updated_at"] = current_time.isoformat()
    elif isinstance(old_cache.get("updated_at"), str):
        next_cache["updated_at"] = old_cache["updated_at"]
    return ServerCachePlan(
        snapshot=result,
        last_good=next_cache,
        changed=changed or not cache_valid,
        bootstrapped_aliases=tuple(bootstrapped),
    )


__all__ = [
    "LAST_GOOD_RELATIVE",
    "SCHEMA_VERSION",
    "ServerCacheError",
    "ServerCachePlan",
    "dump_last_good",
    "last_good_path",
    "prepare_server_refresh",
]
