"""Read-only, runtime-scoped resource observations independent of CRS subscriptions."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import re
from typing import Any, Callable

import yaml

SOURCE_TYPE = "aliyun-shared-traffic"
SOURCE_URL = "https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-queryresourcepackageinstances"
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,47}\Z")
_PROFILE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,47}\Z")
_PACK_ID = re.compile(r"flowpack-[A-Za-z0-9_-]+\Z", re.I)
_UNITS = {"B", "KB", "MB", "GB", "TB", "KiB", "MiB", "GiB", "TiB"}
_MAX_ROWS = 300_000


class _StrictLoader(yaml.SafeLoader):
    pass


def _strict_bool(loader: _StrictLoader, node: yaml.Node) -> bool:
    if node.value not in {"true", "false"}:
        raise ValueError("resource booleans must be true or false")
    return node.value == "true"


def _unique_mapping(loader: _StrictLoader, node: yaml.Node) -> dict:
    pairs = loader.construct_pairs(node, deep=True)
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate resource config key")
        result[key] = value
    return result


_StrictLoader.add_constructor("tag:yaml.org,2002:bool", _strict_bool)
_StrictLoader.add_constructor("tag:yaml.org,2002:map", _unique_mapping)


class ResourceFetchError(Exception):
    """Only the fixed kind may be copied into public state; detail stays private."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail)
        self.kind = kind if kind in {"permission_denied", "auth_error", "network_error", "invalid_data"} else "network_error"


def load_resource_config(path: Path) -> list[dict[str, Any]]:
    """Validate the whole batch before any profile or network access."""
    if not path.exists():
        return []
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("resource subscription config is invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {"sources"} or not isinstance(raw["sources"], list):
        raise ValueError("resource subscription config requires sources")
    result = []
    seen = set()
    for item in raw["sources"]:
        if (not isinstance(item, dict) or set(item) != {"id", "type", "enabled", "profile"}
                or not isinstance(item["id"], str) or not _ID.fullmatch(item["id"])
                or item["id"] in seen or item["type"] != SOURCE_TYPE
                or type(item["enabled"]) is not bool
                or not isinstance(item["profile"], str) or not _PROFILE.fullmatch(item["profile"])):
            raise ValueError("invalid resource subscription source")
        seen.add(item["id"])
        result.append(dict(item))
    if sum(item["enabled"] for item in result) > 1:
        raise ValueError("only one shared traffic source is supported")
    return result


def _utc_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("resource time is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("resource time is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("resource time needs timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _amount(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("resource amount is invalid")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("resource amount is invalid") from exc
    if not number.is_finite() or number < 0 or number > Decimal("1e24"):
        raise ValueError("resource amount is invalid")
    return number


def _number(value: Decimal) -> int | str:
    return int(value) if value == value.to_integral_value() else format(value, "f")


def normalize_package(raw: dict[str, Any]) -> dict[str, Any]:
    """One package is one record; periods, units and coverage never get summed."""
    if not isinstance(raw, dict) or not isinstance(raw.get("InstanceId"), str) or not _PACK_ID.fullmatch(raw["InstanceId"]):
        raise ValueError("invalid shared traffic package ID")
    unit = raw.get("TotalAmountUnit")
    total, remaining = _amount(raw.get("TotalAmount")), _amount(raw.get("RemainingAmount"))
    remaining_unit = raw.get("RemainingAmountUnit")
    # BSS reports an exhausted GB pack as 0 Byte. Zero is unit-independent;
    # nonzero mixed units remain untrusted and are never subtracted.
    if (not isinstance(unit, str) or unit not in _UNITS
            or (remaining_unit != unit and not (remaining == 0 and remaining_unit == "Byte"))):
        raise ValueError("resource units are unknown or mixed")
    if remaining > total:
        raise ValueError("remaining exceeds total")
    used = total - remaining
    # Remark is account-controlled free text; keep it out of durable snapshots.
    region = raw.get("Region")
    region = region if isinstance(region, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", region) else "未知区域"
    return {"id": raw["InstanceId"], "label": "公网共享流量包", "total": _number(total),
            "remaining": _number(remaining), "used": _number(used), "unit": unit,
            "progress_percent": float(used / total * 100) if total else None,
            "effective_at": _utc_time(raw.get("EffectiveTime")),
            "expires_at": _utc_time(raw.get("ExpiryTime")),
            "region": region, "deduct_type": "Absolute" if raw.get("DeductType") == "Absolute" else "未知"}


def query_aliyun_packages(fetch_page: Callable[[int, int], dict], *, page_size: int = 300) -> list[dict]:
    if type(page_size) is not int or not 1 <= page_size <= 300:
        raise ValueError("invalid page size")
    found: list[dict] = []
    seen: set[str] = set()
    expected_total = None
    page = 1
    while True:
        body = fetch_page(page, page_size)
        if not isinstance(body, dict):
            raise ResourceFetchError("invalid_data")
        code = body.get("Code")
        success = body.get("Success")
        if (code is not None and not isinstance(code, str)) or (success is not None and type(success) is not bool):
            raise ResourceFetchError("invalid_data")
        if code != "Success":
            raise ResourceFetchError(_business_error_kind(code))
        if success is not True:
            raise ResourceFetchError("invalid_data")
        data = body.get("Data")
        if not isinstance(data, dict):
            raise ResourceFetchError("invalid_data")
        count = _canonical_uint(data.get("TotalCount"), _MAX_ROWS)
        if count is None or (expected_total is not None and count != expected_total):
            raise ResourceFetchError("invalid_data")
        expected_total = count
        if _canonical_uint(data.get("PageNum"), 1000) != page:
            raise ResourceFetchError("invalid_data")
        if _canonical_uint(data.get("PageSize"), 300) != page_size:
            raise ResourceFetchError("invalid_data")
        instances = data.get("Instances")
        rows = [] if count == 0 and instances is None else instances.get("Instance") if isinstance(instances, dict) else None
        expected_rows = min(page_size, count - (page - 1) * page_size)
        if not isinstance(rows, list) or len(rows) != expected_rows:
            raise ResourceFetchError("invalid_data")
        for row in rows:
            if not isinstance(row, dict):
                raise ResourceFetchError("invalid_data")
            pack_id = row.get("InstanceId")
            if not isinstance(pack_id, str) or not 1 <= len(pack_id) <= 256 or pack_id in seen:
                raise ResourceFetchError("invalid_data")
            seen.add(pack_id)
            # Official resource-pack IDs observed for shared traffic start flowpack-.
            # Never infer traffic use from unrelated storage or CDN commodity codes.
            if _PACK_ID.fullmatch(pack_id) and row.get("Status") == "Available":
                found.append(row)
        if page * page_size >= count:
            break
        if page >= 1000:
            raise ResourceFetchError("invalid_data")
        page += 1
    if len(seen) != expected_total:
        raise ResourceFetchError("invalid_data")
    return found


def _canonical_uint(value: Any, maximum: int) -> int | None:
    if type(value) is int:
        return value if 0 <= value <= maximum else None
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value) and len(value) <= 6:
        parsed = int(value)
        return parsed if parsed <= maximum else None
    return None


def _business_error_kind(code: str | None) -> str:
    if code and ("NotAuthorized" in code or code in {"Forbidden", "AccessDenied", "NoPermission"}):
        return "permission_denied"
    if code and any(token in code for token in ("AccessKey", "Signature", "SecurityToken")):
        return "auth_error"
    return "invalid_data"


def _aliyun_profile(profile: str) -> tuple[str, str]:
    result = None
    try:
        from chatenv import BaseEnvConfig, EnvStore, get_paths, load_config_providers
        load_config_providers()
        matches = [cls for cls in BaseEnvConfig._registry if cls.get_storage_name().lower() == "aliyun"]
        if len(matches) == 1:
            schema = matches[0]
            store = EnvStore(get_paths().envs_dir)
            path = store.profile_path(schema, profile)
            if path.is_file() and not any(part.is_symlink() for part in (path, *path.parents)):
                values = store.load_path(path, interpolate=False)
                fields = {field.env_key for field in schema.get_fields().values()}
                ids = [key for key in fields if key.endswith("ACCESS_KEY_ID")]
                secrets = [key for key in fields if key.endswith("ACCESS_KEY_SECRET")]
                if len(ids) == len(secrets) == 1 and values.get(ids[0]) and values.get(secrets[0]):
                    result = values[ids[0]], values[secrets[0]]
    except Exception:
        pass
    if result is None:
        raise ResourceFetchError("auth_error")
    return result


def fetch_aliyun_shared_traffic(source: dict[str, Any]) -> list[dict]:
    """Official BssOpenApi read only query. No SDK response or exception is logged."""
    kind = None
    try:
        access_id, access_secret = _aliyun_profile(source["profile"])
        from alibabacloud_tea_openapi.client import Client
        from alibabacloud_tea_openapi.models import Config, Params, OpenApiRequest
        from alibabacloud_tea_util.models import RuntimeOptions
        client = Client(Config(access_key_id=access_id, access_key_secret=access_secret,
                               endpoint="business.aliyuncs.com", protocol="HTTPS",
                               connect_timeout=5000, read_timeout=15000))
        params = Params(action="QueryResourcePackageInstances", version="2017-12-14",
                        protocol="HTTPS", pathname="/", method="GET", auth_type="AK",
                        body_type="json", req_body_type="json", style="RPC")
        runtime = RuntimeOptions(connect_timeout=5000, read_timeout=15000)
        def page(number: int, size: int) -> dict:
            response = client.call_api(params, OpenApiRequest(query={"PageNum": str(number), "PageSize": str(size)}), runtime)
            return response.get("body", response)
        return query_aliyun_packages(page)
    except ResourceFetchError as exc:
        kind = exc.kind
    except Exception as exc:
        code = str(getattr(exc, "code", ""))
        kind = _business_error_kind(code) if code else "network_error"
    raise ResourceFetchError(kind or "network_error")


def _selector(source: dict[str, Any]) -> str:
    """Stable nonsecret binding; profile labels never enter public snapshots."""
    identity = f'{source["type"]}\0{source["profile"]}'.encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


def _safe_cached(prior: dict, selector: str, source_type: str) -> tuple[list[dict], str] | None:
    if (prior.get("selector") != selector or prior.get("type") != source_type
            or not (prior.get("status") in {"ok", "empty"} or prior.get("stale") is True)):
        return None
    try:
        observed = prior["last_successful_at"]
        _utc_time(observed)
        rows = prior["records"]
        if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
            return None
        if prior.get("status") == "ok" and not rows:
            return None
        if prior.get("status") == "empty" and rows:
            return None
        safe = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                return None
            normalized = normalize_package({
                "InstanceId": row["id"], "TotalAmount": row["total"],
                "RemainingAmount": row["remaining"], "TotalAmountUnit": row["unit"],
                "RemainingAmountUnit": row["unit"], "EffectiveTime": row["effective_at"],
                "ExpiryTime": row["expires_at"], "Region": row.get("region"),
                "DeductType": row.get("deduct_type"),
            })
            if normalized["id"] in seen or _amount(row["used"]) != _amount(normalized["used"]):
                return None
            if normalized["progress_percent"] is None:
                if row.get("progress_percent") is not None:
                    return None
            elif (abs(_amount(row["progress_percent"]) - Decimal(str(normalized["progress_percent"])))
                  > Decimal("0.000001")):
                return None
            seen.add(normalized["id"])
            safe.append(normalized)
        return safe, observed
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None


def collect_resources(sources: list[dict], previous: list[dict], fetch_source: Callable[[dict], list[dict]], *, now: str) -> list[dict]:
    old = {row.get("id"): row for row in previous if isinstance(row, dict)}
    output = []
    for source in sources:
        if not source["enabled"]:
            continue
        prior = old.get(source["id"], {})
        selector = _selector(source)
        result = {"id": source["id"], "type": source["type"], "label": "阿里云公网共享流量",
                  "scope": "账号级", "source_url": SOURCE_URL, "selector": selector, "checked_at": now,
                  "last_successful_at": None, "stale": False, "records": []}
        try:
            rows = fetch_source(source)
            result["records"] = [normalize_package(row) for row in rows]
            result["status"] = "ok" if result["records"] else "empty"
            result["last_successful_at"] = now
        except ResourceFetchError as exc:
            result["status"] = exc.kind
        except (ValueError, TypeError, KeyError):
            result["status"] = "invalid_data"
        except Exception:
            result["status"] = "network_error"
        if result.get("status") not in {"ok", "empty"}:
            cache = _safe_cached(prior, selector, source["type"])
            if cache is not None:
                result["records"], result["last_successful_at"] = cache
                result["stale"] = True
        output.append(result)
    return output
