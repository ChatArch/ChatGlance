"""Safe, bounded refresh-run journal stored inside a Glance runtime home."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Callable, Iterable, Iterator, Sequence
from uuid import uuid4


SCHEMA_VERSION = 1
HISTORY_OWNER = "chatglance.refresh-history/v1"
HISTORY_RELATIVE = Path("private/refresh-history")
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_BYTES = 256 * 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SOURCES = {"native", "manual", "scheduled", "browser"}
PAGES = {"projects", "servers", "sites", "account-limits"}
TERMINAL_STATUSES = {"success", "partial", "failed", "busy", "interrupted"}
ERROR_TYPES = {
    "busy",
    "collection_error",
    "configuration_error",
    "validation_error",
    "config_changed",
    "publication_error",
    "restart_error",
    "interrupted",
    "internal_error",
}
PHASE_VALUES = {
    "pending",
    "running",
    "completed",
    "passed",
    "published",
    "unchanged",
    "disabled",
    "skipped",
    "not_started",
    "failed",
    "interrupted",
}
COUNT_KEYS = {
    "accounts",
    "failed",
    "ok",
    "online",
    "profiles",
    "repositories",
    "servers",
    "sites",
    "total",
    "visible",
    "visible_repos",
    "with_actual_cli_business_commands",
    "with_actual_cli_tree",
}


class RefreshHistoryError(ValueError):
    """History storage or a requested record failed a safety check."""


def history_root(runtime_home: str | Path) -> Path:
    """Return the package-owned journal directory without creating it."""

    return Path(runtime_home).expanduser() / HISTORY_RELATIVE


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RefreshHistoryError("history timestamps require a timezone")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise RefreshHistoryError("invalid refresh run_id")
    return run_id


def new_run_id(now: datetime | None = None) -> str:
    """Generate a sortable, path-safe run identifier."""

    moment = _aware(now or datetime.now(timezone.utc))
    return moment.strftime("%Y%m%dT%H%M%S%fZ-") + uuid4().hex[:16]


def _check_directory(path: Path, *, create: bool) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if not create:
            return False
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            metadata = path.lstat()
        else:
            metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise RefreshHistoryError(f"history directory must not be a symlink: {path.name}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise RefreshHistoryError(f"history path must be a directory: {path.name}")
    if create:
        path.chmod(0o700)
    return True


def _directories(runtime_home: str | Path, *, create: bool) -> tuple[Path, Path, Path] | None:
    root = Path(runtime_home).expanduser()
    if not _check_directory(root, create=False):
        if not create:
            return None
        raise RefreshHistoryError("runtime home must already exist")
    private = root / "private"
    if not _check_directory(private, create=create):
        return None
    base = private / "refresh-history"
    if not _check_directory(base, create=create):
        return None
    runs = base / "runs"
    snapshots = base / "snapshots"
    if not _check_directory(runs, create=create) or not _check_directory(snapshots, create=create):
        return None
    return base, runs, snapshots


@contextmanager
def _journal_lock(runtime_home: str | Path, *, create: bool = True) -> Iterator[tuple[Path, Path, Path]]:
    directories = _directories(runtime_home, create=create)
    if directories is None:
        raise RefreshHistoryError("refresh history does not exist")
    base, runs, snapshots = directories
    lock_path = base / "journal.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RefreshHistoryError("history journal lock is unavailable or unsafe") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RefreshHistoryError("history journal lock must be a regular file")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
            descriptor = -1
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield base, runs, snapshots
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    parent = path.parent
    metadata = parent.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RefreshHistoryError("history destination parent is unsafe")
    if path.exists() or path.is_symlink():
        existing = path.lstat()
        if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
            raise RefreshHistoryError("history destination must be a regular file")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parent, prefix=".history-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)
    path.chmod(0o600)
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_json(path: Path, *, maximum: int = MAX_RECORD_BYTES) -> dict[str, Any] | None:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _owned_record(value: dict[str, Any] | None, *, run_id: str | None = None) -> bool:
    if not isinstance(value, dict) or value.get("owner") != HISTORY_OWNER or value.get("schema_version") != SCHEMA_VERSION:
        return False
    candidate = value.get("run_id")
    return isinstance(candidate, str) and bool(RUN_ID_RE.fullmatch(candidate)) and (run_id is None or candidate == run_id)


def _valid_run_record(value: dict[str, Any] | None, *, run_id: str | None = None) -> bool:
    if not _owned_record(value, run_id=run_id):
        return False
    assert value is not None
    allowed = {
        "owner", "schema_version", "run_id", "source", "status", "requested_pages",
        "started_at", "finished_at", "elapsed_ms", "process", "pages", "phases",
        "changed", "published", "restarted", "error_type", "backup_id",
    }
    if not set(value) <= allowed or value.get("source") not in SOURCES:
        return False
    if value.get("status") not in {"running", *TERMINAL_STATUSES}:
        return False
    requested = value.get("requested_pages")
    if not isinstance(requested, list) or requested != list(dict.fromkeys(requested)) or any(page not in PAGES for page in requested):
        return False
    if _parse_time(value.get("started_at")) is None:
        return False
    process = value.get("process")
    if not isinstance(process, dict) or not isinstance(process.get("pid"), int) or not isinstance(process.get("start"), str):
        return False
    owner_lock = process.get("owner_lock")
    if not isinstance(owner_lock, dict) or not isinstance(owner_lock.get("device"), int) or not isinstance(owner_lock.get("inode"), int):
        return False
    if set(process) - {"pid", "start", "owner_lock", "refresh_lock"}:
        return False
    refresh_lock = process.get("refresh_lock")
    if refresh_lock is not None and (
        not isinstance(refresh_lock, dict)
        or not isinstance(refresh_lock.get("device"), int)
        or not isinstance(refresh_lock.get("inode"), int)
        or set(refresh_lock) != {"device", "inode"}
    ):
        return False
    pages = value.get("pages")
    if not isinstance(pages, list) or _sanitize_pages(pages) != pages:
        return False
    phases = value.get("phases")
    if not isinstance(phases, dict) or set(phases) != {"collection", "validation", "publication", "restart"}:
        return False
    if any(phase not in PHASE_VALUES for phase in phases.values()):
        return False
    if not all(value.get(key) is None or type(value.get(key)) is bool for key in ("changed", "published", "restarted")):
        return False
    if value.get("error_type") is not None and value.get("error_type") not in ERROR_TYPES:
        return False
    backup_id = value.get("backup_id")
    if backup_id is not None and (not isinstance(backup_id, str) or not re.fullmatch(r"refresh-[A-Za-z0-9._-]{1,160}", backup_id)):
        return False
    if value["status"] == "running":
        return "finished_at" not in value and "elapsed_ms" not in value
    return (
        _parse_time(value.get("finished_at")) is not None
        and isinstance(value.get("elapsed_ms"), int)
        and not isinstance(value.get("elapsed_ms"), bool)
        and value["elapsed_ms"] >= 0
    )


def _process_start(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        # The command name can contain spaces and parentheses.  Fields after the
        # final ')' begin with process state; kernel field 22 is offset 19 here.
        remainder = text[text.rfind(")") + 2 :].split()
        return remainder[19]
    except (OSError, IndexError, ValueError):
        return None


def _lock_owner_pids(device: int, inode: int) -> set[int] | None:
    try:
        lines = Path("/proc/locks").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    owners: set[int] = set()
    for line in lines:
        fields = line.split()
        if len(fields) < 6:
            continue
        try:
            pid = int(fields[4])
            major_text, minor_text, inode_text = fields[5].split(":", 2)
            candidate_device = os.makedev(int(major_text, 16), int(minor_text, 16))
            candidate_inode = int(inode_text)
        except (ValueError, OSError):
            continue
        if candidate_device == device and candidate_inode == inode:
            owners.add(pid)
    return owners


def _lock_evidence_active(path: Path, evidence: Any, pid: int) -> bool:
    if not isinstance(evidence, dict) or not isinstance(evidence.get("device"), int) or not isinstance(evidence.get("inode"), int):
        return False
    try:
        metadata = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return False
    if metadata.st_dev != evidence["device"] or metadata.st_ino != evidence["inode"]:
        return False
    owners = _lock_owner_pids(metadata.st_dev, metadata.st_ino)
    if owners is not None:
        return pid in owners
    flags = os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            return False
    finally:
        os.close(descriptor)


def _record_active(runtime_home: str | Path, record: dict[str, Any]) -> bool:
    if record.get("status") != "running":
        return False
    process = record.get("process")
    if not isinstance(process, dict) or not isinstance(process.get("pid"), int) or not isinstance(process.get("start"), str):
        return False
    pid = process["pid"]
    if _process_start(pid) != process["start"]:
        return False
    lock = process.get("refresh_lock")
    if lock is None:
        # Before the runtime refresh lock is acquired, a per-run owner lease
        # proves that this exact process still owns the starting record.
        owner_path = history_root(runtime_home) / f"active-{record.get('run_id', '')}.lock"
        return _lock_evidence_active(owner_path, process.get("owner_lock"), pid)
    lock_path = Path(runtime_home).expanduser() / "logs/refresh-live-pages.lock"
    return _lock_evidence_active(lock_path, lock, pid)


def _elapsed_ms(record: dict[str, Any], finished: datetime) -> int:
    started = _parse_time(record.get("started_at"))
    if started is None:
        return 0
    return max(0, int((_aware(finished) - started).total_seconds() * 1000))


def _sanitize_counts(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int | float] = {}
    for key in sorted(COUNT_KEYS):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        if item < 0 or isinstance(item, float) and not math.isfinite(item):
            continue
        result[key] = item
    return result


def _sanitize_pages(pages: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in pages:
        if not isinstance(raw, dict) or raw.get("page") not in PAGES or raw.get("status") not in {"ok", "partial", "error"}:
            continue
        row: dict[str, Any] = {"page": raw["page"], "status": raw["status"]}
        if raw["status"] == "error":
            row["error_type"] = "collection_error"
        counts = _sanitize_counts(raw.get("counts"))
        if counts:
            row["counts"] = counts
        generated = raw.get("generated_at")
        if _parse_time(generated) is not None:
            row["generated_at"] = generated
        result.append(row)
    return result


def _phase(value: str | None, fallback: str) -> str:
    candidate = value or fallback
    if candidate not in PHASE_VALUES:
        raise RefreshHistoryError("invalid journal phase status")
    return candidate


def _record_path(runs: Path, run_id: str) -> Path:
    return runs / f"{_validate_run_id(run_id)}.json"


class RefreshHistory:
    """Serialize trusted refresh facts without accepting arbitrary text."""

    def __init__(self, runtime_home: str | Path, *, now: Callable[[], datetime] | None = None):
        self.runtime_home = Path(runtime_home).expanduser()
        self._clock = now or (lambda: datetime.now(timezone.utc))
        self._leases: dict[str, tuple[Any, Path, int, int]] = {}

    def _now(self) -> datetime:
        return _aware(self._clock())

    def _acquire_owner_lease(self, base: Path, run_id: str) -> dict[str, int]:
        path = base / f"active-{run_id}.lock"
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise RefreshHistoryError("refresh owner lease is unavailable or unsafe") from exc
        handle = None
        try:
            os.fchmod(descriptor, 0o600)
            handle = os.fdopen(descriptor, "a+", encoding="utf-8")
            descriptor = -1
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            metadata = os.fstat(handle.fileno())
            self._leases[run_id] = (handle, path, metadata.st_dev, metadata.st_ino)
            return {"device": metadata.st_dev, "inode": metadata.st_ino}
        except BaseException:
            if handle is not None:
                handle.close()
            elif descriptor >= 0:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise

    def _release_owner_lease(self, run_id: str) -> None:
        lease = self._leases.pop(run_id, None)
        if lease is None:
            return
        handle, path, device, inode = lease
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()
        try:
            metadata = path.lstat()
            if not stat.S_ISLNK(metadata.st_mode) and stat.S_ISREG(metadata.st_mode) and metadata.st_dev == device and metadata.st_ino == inode:
                path.unlink()
        except FileNotFoundError:
            pass

    def _cleanup_stale_owner_lease(self, base: Path, record: dict[str, Any]) -> None:
        process = record.get("process")
        evidence = process.get("owner_lock") if isinstance(process, dict) else None
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not isinstance(evidence, dict):
            return
        path = base / f"active-{run_id}.lock"
        try:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                return
            if metadata.st_dev != evidence.get("device") or metadata.st_ino != evidence.get("inode"):
                return
            flags = os.O_RDWR | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0)
            descriptor = os.open(path, flags)
        except OSError:
            return
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            path.unlink(missing_ok=True)
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def _cleanup_orphan_owner_leases(self, base: Path, runs: Path) -> None:
        for path in base.glob("active-*.lock"):
            name = path.name
            run_id = name[len("active-") : -len(".lock")] if name.endswith(".lock") else ""
            if not RUN_ID_RE.fullmatch(run_id):
                continue
            try:
                metadata = path.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    continue
            except OSError:
                continue
            record = _read_json(_record_path(runs, run_id))
            process = record.get("process") if _valid_run_record(record, run_id=run_id) and record.get("status") == "running" else None
            evidence = process.get("owner_lock") if isinstance(process, dict) else None
            if isinstance(evidence, dict) and evidence.get("device") == metadata.st_dev and evidence.get("inode") == metadata.st_ino:
                continue
            flags = os.O_RDWR | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0)
            try:
                descriptor = os.open(path, flags)
            except OSError:
                continue
            try:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                path.unlink(missing_ok=True)
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _recover_locked(self, base: Path, runs: Path, moment: datetime) -> None:
        self._cleanup_orphan_owner_leases(base, runs)
        for path in runs.glob("*.json"):
            run_id = path.stem
            if not RUN_ID_RE.fullmatch(run_id):
                continue
            record = _read_json(path)
            if not _valid_run_record(record, run_id=run_id) or record.get("status") != "running":
                continue
            if _record_active(self.runtime_home, record):
                continue
            recovered = deepcopy(record)
            recovered["status"] = "interrupted"
            recovered["error_type"] = "interrupted"
            recovered["finished_at"] = _iso(moment)
            recovered["elapsed_ms"] = _elapsed_ms(recovered, moment)
            phases = recovered.get("phases") if isinstance(recovered.get("phases"), dict) else {}
            recovered["phases"] = {
                key: "interrupted" if phases.get(key) == "running"
                else "not_started" if phases.get(key) == "pending"
                else phases.get(key, "not_started")
                for key in ("collection", "validation", "publication", "restart")
            }
            _atomic_json(path, recovered)
            self._cleanup_stale_owner_lease(base, recovered)

    def start(self, source: str, pages: Sequence[str], *, run_id: str | None = None) -> str:
        if source not in SOURCES:
            raise RefreshHistoryError("invalid refresh source")
        requested = list(dict.fromkeys(pages))
        if any(page not in PAGES for page in requested):
            raise RefreshHistoryError("invalid requested refresh pages")
        moment = self._now()
        identifier = _validate_run_id(run_id) if run_id is not None else new_run_id(moment)
        pid = os.getpid()
        process_start = _process_start(pid)
        if process_start is None:
            raise RefreshHistoryError("could not establish process identity")
        with _journal_lock(self.runtime_home) as (base, runs, _snapshots):
            self._recover_locked(base, runs, moment)
            path = _record_path(runs, identifier)
            if path.exists() or path.is_symlink():
                existing = _read_json(path)
                if _valid_run_record(existing, run_id=identifier) and existing.get("status") == "running" and _record_active(self.runtime_home, existing):
                    raise RefreshHistoryError("refresh run_id is already active")
                raise RefreshHistoryError("refresh run_id already exists")
            owner_lock = self._acquire_owner_lease(base, identifier)
            record = {
                "owner": HISTORY_OWNER,
                "schema_version": SCHEMA_VERSION,
                "run_id": identifier,
                "source": source,
                "status": "running",
                "requested_pages": requested,
                "started_at": _iso(moment),
                "process": {"pid": pid, "start": process_start, "owner_lock": owner_lock},
                "pages": [],
                "phases": {
                    "collection": "pending",
                    "validation": "pending",
                    "publication": "pending",
                    "restart": "pending",
                },
                "changed": False,
                "published": False,
                "restarted": False,
            }
            try:
                _atomic_json(path, record)
                _atomic_json(base / "latest.json", record)
            except BaseException:
                self._release_owner_lease(identifier)
                raise
        return identifier

    def acquired(self, run_id: str, refresh_lock: str | Path) -> dict[str, Any]:
        identifier = _validate_run_id(run_id)
        lock_path = Path(refresh_lock)
        expected = self.runtime_home / "logs/refresh-live-pages.lock"
        try:
            if lock_path.resolve(strict=True) != expected.resolve(strict=True):
                raise RefreshHistoryError("refresh lock evidence does not match the runtime")
            metadata = lock_path.lstat()
        except OSError as exc:
            raise RefreshHistoryError("refresh lock evidence is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise RefreshHistoryError("refresh lock evidence is unsafe")
        with _journal_lock(self.runtime_home) as (base, runs, _snapshots):
            path = _record_path(runs, identifier)
            record = _read_json(path)
            if not _valid_run_record(record, run_id=identifier) or record.get("status") != "running":
                raise RefreshHistoryError("active refresh record is unavailable")
            updated = deepcopy(record)
            process = deepcopy(updated["process"])
            process["refresh_lock"] = {"device": metadata.st_dev, "inode": metadata.st_ino}
            updated["process"] = process
            updated["phases"]["collection"] = "running"
            _atomic_json(path, updated)
            _atomic_json(base / "latest.json", updated)
            return updated

    def checkpoint(
        self,
        run_id: str,
        *,
        requested_pages: Sequence[str] | None = None,
        pages: Iterable[dict[str, Any]] | None = None,
        collection: str | None = None,
        validation: str | None = None,
        publication: str | None = None,
        restart: str | None = None,
        changed: bool | None = False,
        published: bool | None = False,
        restarted: bool | None = False,
        backup_id: str | None = None,
    ) -> dict[str, Any]:
        """Durably record allowlisted facts while a run remains active."""

        identifier = _validate_run_id(run_id)
        if not all(value is None or type(value) is bool for value in (changed, published, restarted)):
            raise RefreshHistoryError("journal publication facts must be boolean or unknown")
        if backup_id is not None and not re.fullmatch(r"refresh-[A-Za-z0-9._-]{1,160}", backup_id):
            raise RefreshHistoryError("invalid backup identifier")
        requested = None if requested_pages is None else list(dict.fromkeys(requested_pages))
        if requested is not None and any(page not in PAGES for page in requested):
            raise RefreshHistoryError("invalid requested refresh pages")
        with _journal_lock(self.runtime_home) as (base, runs, _snapshots):
            path = _record_path(runs, identifier)
            record = _read_json(path)
            if not _valid_run_record(record, run_id=identifier) or record.get("status") != "running":
                raise RefreshHistoryError("active refresh record is unavailable")
            updated = deepcopy(record)
            if requested is not None:
                updated["requested_pages"] = requested
            if pages is not None:
                updated["pages"] = _sanitize_pages(pages)
            for key, value in {
                "collection": collection, "validation": validation,
                "publication": publication, "restart": restart,
            }.items():
                if value is not None:
                    updated["phases"][key] = _phase(value, "pending")
            updated.update({"changed": changed, "published": published, "restarted": restarted})
            if backup_id is not None:
                updated["backup_id"] = backup_id
            _atomic_json(path, updated)
            _atomic_json(base / "latest.json", updated)
            return updated

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        pages: Iterable[dict[str, Any]] = (),
        error_type: str | None = None,
        validation: str | None = None,
        publication: str | None = None,
        restart: str | None = None,
        changed: bool = False,
        published: bool = False,
        restarted: bool = False,
        backup_id: str | None = None,
    ) -> dict[str, Any]:
        identifier = _validate_run_id(run_id)
        if status not in TERMINAL_STATUSES:
            raise RefreshHistoryError("invalid terminal refresh status")
        if error_type is not None and error_type not in ERROR_TYPES:
            raise RefreshHistoryError("invalid refresh error type")
        if not all(type(value) is bool for value in (changed, published, restarted)):
            raise RefreshHistoryError("journal publication flags must be boolean")
        if backup_id is not None and (not isinstance(backup_id, str) or not re.fullmatch(r"refresh-[A-Za-z0-9._-]{1,160}", backup_id)):
            raise RefreshHistoryError("invalid backup identifier")
        moment = self._now()
        with _journal_lock(self.runtime_home) as (base, runs, snapshots):
            path = _record_path(runs, identifier)
            record = _read_json(path)
            recoverable_interruption = (
                _valid_run_record(record, run_id=identifier)
                and record.get("status") == "interrupted"
                and isinstance(record.get("process"), dict)
                and record["process"].get("pid") == os.getpid()
                and record["process"].get("start") == _process_start(os.getpid())
            )
            if not _valid_run_record(record, run_id=identifier) or (
                record.get("status") != "running" and not recoverable_interruption
            ):
                raise RefreshHistoryError("active refresh record is unavailable")
            safe_pages = _sanitize_pages(pages)
            phases = record.get("phases") if isinstance(record.get("phases"), dict) else {}
            if status == "busy":
                collection_default = "not_started"
            elif status == "interrupted":
                collection_default = "interrupted"
            elif not safe_pages and error_type in {"configuration_error", "internal_error"}:
                collection_default = "not_started"
            else:
                collection_default = "completed"
            updated = deepcopy(record)
            updated.update(
                {
                    "status": status,
                    "pages": safe_pages,
                    "phases": {
                        "collection": _phase(phases.get("collection") if phases.get("collection") not in {"pending", "running"} else None, collection_default),
                        "validation": _phase(validation, "skipped"),
                        "publication": _phase(publication, "skipped"),
                        "restart": _phase(restart, "skipped"),
                    },
                    "changed": changed,
                    "published": published,
                    "restarted": restarted,
                    "finished_at": _iso(moment),
                    "elapsed_ms": _elapsed_ms(record, moment),
                }
            )
            if error_type is not None:
                updated["error_type"] = error_type
            else:
                updated.pop("error_type", None)
            if backup_id is not None:
                updated["backup_id"] = backup_id
            else:
                updated.pop("backup_id", None)
            try:
                _atomic_json(path, updated)
                _atomic_json(base / "latest.json", updated)
                if published:
                    snapshot = {
                        "owner": HISTORY_OWNER,
                        "schema_version": SCHEMA_VERSION,
                        "run_id": identifier,
                        "generated_at": updated["finished_at"],
                        "pages": safe_pages,
                        "backup_id": updated.get("backup_id"),
                    }
                    _atomic_json(snapshots / f"{identifier}.json", snapshot)
            finally:
                self._release_owner_lease(identifier)
        self._automatic_prune()
        return updated

    def _automatic_prune(self) -> None:
        from .config import history_settings

        try:
            settings = history_settings()
            prune_refresh_history(self.runtime_home, apply=True, **settings)
        except (OSError, ValueError, RefreshHistoryError):
            # The completed record remains durable.  Explicit CLI/API pruning
            # reports malformed policy or storage instead of hiding it.
            return


def record_rejected_run(
    runtime_home: str | Path,
    source: str,
    pages: Sequence[str],
    *,
    error_type: str = "busy",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Append a rejected attempt (including browser/native busy outcomes)."""

    history = RefreshHistory(runtime_home)
    identifier = history.start(source, pages, run_id=run_id)
    return history.finish(
        identifier,
        status="busy" if error_type == "busy" else "failed",
        error_type=error_type,
        validation="not_started",
        publication="not_started",
        restart="not_started",
    )


def _readonly_directories(runtime_home: str | Path) -> tuple[Path, Path, Path] | None:
    return _directories(runtime_home, create=False)


def _effective(runtime_home: str | Path, record: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(record)
    status = result.get("status")
    result["effective_status"] = "running" if status == "running" and _record_active(runtime_home, result) else "interrupted" if status == "running" else status
    return result


def list_refresh_runs(runtime_home: str | Path, *, limit: int = 100) -> list[dict[str, Any]]:
    """Read newest owned records without repairing or writing anything."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10000:
        raise RefreshHistoryError("history list limit must be between 1 and 10000")
    directories = _readonly_directories(runtime_home)
    if directories is None:
        return []
    _base, runs, _snapshots = directories
    records: list[dict[str, Any]] = []
    for path in runs.glob("*.json"):
        run_id = path.stem
        if not RUN_ID_RE.fullmatch(run_id):
            continue
        record = _read_json(path)
        if _valid_run_record(record, run_id=run_id):
            records.append(_effective(runtime_home, record))
    records.sort(key=lambda item: (str(item.get("started_at", "")), item["run_id"]), reverse=True)
    return records[:limit]


def show_refresh_run(runtime_home: str | Path, run_id: str) -> dict[str, Any]:
    """Read one owned record by a strictly path-safe identifier."""

    identifier = _validate_run_id(run_id)
    directories = _readonly_directories(runtime_home)
    if directories is None:
        raise RefreshHistoryError("refresh run was not found")
    _base, runs, _snapshots = directories
    record = _read_json(_record_path(runs, identifier))
    if not _valid_run_record(record, run_id=identifier):
        raise RefreshHistoryError("refresh run was not found or is not package-owned")
    return _effective(runtime_home, record)


def _last_good_run_ids(runtime_home: str | Path) -> set[str]:
    path = Path(runtime_home).expanduser() / "private/server-last-good.json"
    value = _read_json(path, maximum=16 * 1024 * 1024) if path.exists() or path.is_symlink() else None
    result: set[str] = set()
    if not isinstance(value, dict) or not isinstance(value.get("servers"), dict):
        return result
    for entry in value["servers"].values():
        run_id = entry.get("run_id") if isinstance(entry, dict) else None
        if isinstance(run_id, str) and RUN_ID_RE.fullmatch(run_id):
            result.add(run_id)
    return result


def _owned_snapshot(path: Path, run_id: str) -> bool:
    value = _read_json(path)
    if not _owned_record(value, run_id=run_id):
        return False
    allowed = {"owner", "schema_version", "run_id", "generated_at", "pages", "backup_id"}
    backup_id = value.get("backup_id")
    valid_backup = backup_id is None or isinstance(backup_id, str) and bool(re.fullmatch(r"refresh-[A-Za-z0-9._-]{1,160}", backup_id))
    return (
        set(value) <= allowed
        and isinstance(value.get("pages"), list)
        and _sanitize_pages(value["pages"]) == value["pages"]
        and _parse_time(value.get("generated_at")) is not None
        and valid_backup
    )


def prune_refresh_history(
    runtime_home: str | Path,
    *,
    retention_days: int | None = None,
    max_bytes: int | None = None,
    apply: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Preview or delete only confirmed-owned run bundles.

    Age and aggregate-byte policies are both enforced.  The latest attempt,
    active/future runs, the newest published rollback point, and runs named by
    last-good entries remain protected even when that leaves the store over its
    configured cap.
    """

    if retention_days is None or max_bytes is None:
        from .config import history_settings

        settings = history_settings()
        retention_days = settings["retention_days"] if retention_days is None else retention_days
        max_bytes = settings["max_bytes"] if max_bytes is None else max_bytes
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
        raise RefreshHistoryError("retention_days must be a positive integer")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise RefreshHistoryError("max_bytes must be a positive integer")
    if type(apply) is not bool:
        raise RefreshHistoryError("apply must be boolean")
    moment = _aware(now or datetime.now(timezone.utc))
    directories = _readonly_directories(runtime_home)
    if directories is None:
        return {
            "applied": apply,
            "retention_days": retention_days,
            "max_bytes": max_bytes,
            "before_bytes": 0,
            "after_bytes": 0,
            "delete_run_ids": [],
            "protected_run_ids": [],
            "over_limit": False,
        }

    with _journal_lock(runtime_home, create=False) as (base, runs, snapshots):
        records: dict[str, dict[str, Any]] = {}
        bundles: dict[str, list[Path]] = {}
        sizes: dict[str, int] = {}
        for path in runs.glob("*.json"):
            run_id = path.stem
            if not RUN_ID_RE.fullmatch(run_id):
                continue
            record = _read_json(path)
            if not _valid_run_record(record, run_id=run_id):
                continue
            records[run_id] = record
            bundle: list[Path] = []
            snapshot = snapshots / f"{run_id}.json"
            if snapshot.exists() and _owned_snapshot(snapshot, run_id):
                bundle.append(snapshot)
            bundle.append(path)
            bundles[run_id] = bundle
            sizes[run_id] = sum(item.stat().st_size for item in bundle)

        snapshot_times: dict[str, datetime] = {}
        for snapshot in snapshots.glob("*.json"):
            run_id = snapshot.stem
            if not RUN_ID_RE.fullmatch(run_id) or not _owned_snapshot(snapshot, run_id):
                continue
            value = _read_json(snapshot)
            assert value is not None
            generated = _parse_time(value.get("generated_at"))
            if generated is None:
                continue
            snapshot_times[run_id] = generated
            if run_id not in bundles:
                bundles[run_id] = [snapshot]
                sizes[run_id] = snapshot.stat().st_size

        latest = _read_json(base / "latest.json")
        latest_size = (base / "latest.json").stat().st_size if _valid_run_record(latest) else 0
        before_bytes = latest_size + sum(sizes.values())
        protected = _last_good_run_ids(runtime_home)
        if _valid_run_record(latest):
            protected.add(latest["run_id"])
        for run_id, record in records.items():
            if _record_active(runtime_home, record):
                protected.add(run_id)
            timestamps = [_parse_time(record.get("started_at")), _parse_time(record.get("finished_at"))]
            if any(timestamp is None for timestamp in timestamps[:1]) or any(timestamp is not None and timestamp > moment + timedelta(minutes=5) for timestamp in timestamps):
                protected.add(run_id)
        for run_id, timestamp in snapshot_times.items():
            if timestamp > moment + timedelta(minutes=5):
                protected.add(run_id)
        published = [
            (str(record.get("finished_at", "")), run_id)
            for run_id, record in records.items()
            if record.get("published") is True
        ]
        if published:
            protected.add(max(published)[1])
        if snapshot_times:
            protected.add(max((timestamp, run_id) for run_id, timestamp in snapshot_times.items())[1])

        cutoff = moment - timedelta(days=retention_days)
        delete: set[str] = set()
        for run_id, record in records.items():
            if run_id in protected:
                continue
            timestamp = _parse_time(record.get("finished_at")) or _parse_time(record.get("started_at"))
            if timestamp is not None and timestamp < cutoff:
                delete.add(run_id)
        for run_id, timestamp in snapshot_times.items():
            if run_id not in records and run_id not in protected and timestamp < cutoff:
                delete.add(run_id)

        remaining = before_bytes - sum(sizes.get(run_id, 0) for run_id in delete)
        candidates = sorted(
            (
                (_parse_time(record.get("finished_at")) or _parse_time(record.get("started_at"))
                 or snapshot_times.get(run_id) or datetime.max.replace(tzinfo=timezone.utc), run_id)
                for run_id in bundles
                if run_id not in protected and run_id not in delete
                for record in [records.get(run_id, {})]
            ),
            key=lambda item: (item[0], item[1]),
        )
        for _timestamp_value, run_id in candidates:
            if remaining <= max_bytes:
                break
            delete.add(run_id)
            remaining -= sizes.get(run_id, 0)

        delete_ids = sorted(
            delete,
            key=lambda run_id: (
                str(records.get(run_id, {}).get("started_at", snapshot_times.get(run_id, ""))), run_id
            ),
        )
        if apply:
            for run_id in delete_ids:
                for path in bundles.get(run_id, []):
                    try:
                        metadata = path.lstat()
                        if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                            path.unlink()
                    except FileNotFoundError:
                        continue
            descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        after_bytes = before_bytes - sum(sizes.get(run_id, 0) for run_id in delete)
        return {
            "applied": apply,
            "retention_days": retention_days,
            "max_bytes": max_bytes,
            "before_bytes": before_bytes,
            "after_bytes": after_bytes,
            "delete_run_ids": delete_ids,
            "protected_run_ids": sorted(run_id for run_id in protected if run_id in bundles),
            "over_limit": after_bytes > max_bytes,
        }


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_RETENTION_DAYS",
    "HISTORY_OWNER",
    "RefreshHistory",
    "RefreshHistoryError",
    "history_root",
    "list_refresh_runs",
    "new_run_id",
    "prune_refresh_history",
    "record_rejected_run",
    "show_refresh_run",
]
