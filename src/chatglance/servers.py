"""Build and collect ChatArch server-status pages for Glance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import html
import ipaddress
import json
from pathlib import Path
import re
import shlex
import socket
import subprocess
from typing import Any, Iterable, cast

SERVER_PAGE_NAME = "服务器"
LEGACY_SERVER_PAGE_NAMES = {"Servers", "Server Status", "服务器状态"}

REMOTE_PROBE_SCRIPT = r'''
printf '@@chatglance:meta@@\n'
printf 'hostname=%s\n' "$(hostname 2>/dev/null || true)"
printf 'user=%s\n' "$(id -un 2>/dev/null || true)"
printf 'kernel=%s\n' "$(uname -srmo 2>/dev/null || uname -a 2>/dev/null || true)"
printf 'ips=%s\n' "$(hostname -I 2>/dev/null || true)"
printf 'collected_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || true)"

printf '@@chatglance:cpu@@\n'
printf 'cores=%s\n' "$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
printf 'loadavg=%s\n' "$(cat /proc/loadavg 2>/dev/null || uptime 2>/dev/null || true)"
if [ -r /proc/stat ]; then
  read _ u1 n1 s1 i1 w1 irq1 sirq1 steal1 rest1 < /proc/stat
  sleep 0.20
  read _ u2 n2 s2 i2 w2 irq2 sirq2 steal2 rest2 < /proc/stat
  printf 'stat1=%s %s %s %s %s %s %s %s\n' "$u1" "$n1" "$s1" "$i1" "$w1" "$irq1" "$sirq1" "$steal1"
  printf 'stat2=%s %s %s %s %s %s %s %s\n' "$u2" "$n2" "$s2" "$i2" "$w2" "$irq2" "$sirq2" "$steal2"
fi

printf '@@chatglance:meminfo@@\n'
cat /proc/meminfo 2>/dev/null || true

printf '@@chatglance:df@@\n'
df -PT -B1 -x tmpfs -x devtmpfs -x overlay -x squashfs -x efivarfs -x cgroup2 -x proc -x sysfs -x securityfs -x debugfs -x tracefs 2>/dev/null || df -P -k 2>/dev/null || true

printf '@@chatglance:lsblk@@\n'
lsblk -b -P -o NAME,TYPE,SIZE,MOUNTPOINT,FSTYPE,MODEL,TRAN,ROTA,RM 2>/dev/null || true

printf '@@chatglance:readonly_devices@@\n'
for sysdev in /sys/block/*; do
  [ -e "$sysdev" ] || continue
  dev="${sysdev##*/}"
  case "$dev" in loop*|ram*) continue ;; esac
  rotational=""
  [ -r "$sysdev/queue/rotational" ] && rotational="$(cat "$sysdev/queue/rotational" 2>/dev/null || true)"
  size="$(lsblk -dn -o SIZE "/dev/$dev" 2>/dev/null || true)"
  mountpoints="$(lsblk -nr -o MOUNTPOINT "/dev/$dev" 2>/dev/null | tr '\n' ',' || true)"
  lvm="$(lsblk -nr -o NAME,TYPE "/dev/$dev" 2>/dev/null | while read name type; do [ "$type" = lvm ] && printf '%s,' "$name"; done || true)"
  printf 'device=%s rotational=%s size=%s lvm=%s mountpoints=%s\n' "$dev" "$rotational" "$size" "$lvm" "$mountpoints"
done

printf '@@chatglance:getdevices_script@@\n'
getdevices_script="$(find "$HOME" /opt /usr/local/bin -maxdepth 5 -type f -name getdevices.sh 2>/dev/null | head -n 1 || true)"
if [ -n "$getdevices_script" ]; then
  if command -v smartctl >/dev/null 2>&1; then
    timeout 25 bash "$getdevices_script" 2>/dev/null || true
  else
    printf 'SKIPPED smartctl unavailable\n'
  fi
else
  printf 'SKIPPED getdevices.sh unavailable\n'
fi

printf '@@chatglance:gpu@@\n'
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu --format=csv,noheader,nounits 2>/dev/null || true
fi
printf '@@chatglance:lspci@@\n'
if command -v lspci >/dev/null 2>&1; then
  lspci 2>/dev/null || true
fi
'''

EXCLUDED_ALIASES = {
    "local",
    "localhost",
    "rexpc",
    "rex.mini",
    "mini.frp",
    "zhihong.oray",
    "rexwzh.oray",
    "cubebot.oray",
    "zhihong.lean4web",
    "azure.cn",
    "essay.newaliyun",
    "root.ctyun",
    "rex.ctyun",
    "zhihong.tencent",
}

PUBLIC_ALIAS_MARKERS = ("tencent", "aliyun", "ctyun", "azure", "newazure", "newaliyun", "tencent.am")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_server_status(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("server status JSON must be an object")
    if not isinstance(data.get("servers"), list):
        raise ValueError("server status JSON must contain a servers list")
    return data


def dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def text_value(value: Any, fallback: str = "—") -> str:
    text = str(value or "").strip()
    return text or fallback


def html_text(value: Any, fallback: str = "—") -> str:
    return html.escape(text_value(value, fallback), quote=True)


def format_bytes(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number < 0:
        return "—"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    unit = "B"
    for unit in units:
        if number < 1024 or unit == units[-1]:
            break
        number /= 1024
    if unit == "B":
        return f"{int(number)} {unit}"
    return f"{number:.1f} {unit}"


def format_percent(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "—"


def parse_sections(output: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.rstrip("\n")
        if line.startswith("@@chatglance:") and line.endswith("@@"):
            current = line.removeprefix("@@chatglance:").removesuffix("@@")
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return sections


def parse_key_values(lines: Iterable[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def parse_meminfo(lines: Iterable[str]) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        match = re.search(r"\d+", rest)
        if match:
            values[key] = int(match.group(0)) * 1024
    return values


def parse_df(lines: Iterable[str]) -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    skip_prefixes = ("/run", "/var/lib/docker", "/var/lib/containerd", "/snap")
    for line in lines:
        if not line.strip() or line.startswith("Filesystem"):
            continue
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        filesystem, fs_type, size, used, available, used_percent, mountpoint = parts
        if mountpoint.startswith(skip_prefixes):
            continue
        try:
            size_bytes = int(size)
            used_bytes = int(used)
            available_bytes = int(available)
        except ValueError:
            continue
        try:
            percent: float | None = float(used_percent.rstrip("%"))
        except ValueError:
            percent = None
        disks.append(
            {
                "filesystem": filesystem,
                "type": fs_type,
                "mountpoint": mountpoint,
                "size_bytes": size_bytes,
                "used_bytes": used_bytes,
                "available_bytes": available_bytes,
                "used_percent": percent,
            }
        )
    return sorted(disks, key=lambda item: (item.get("mountpoint") != "/", str(item.get("mountpoint", ""))))


def parse_lsblk(lines: Iterable[str]) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    skipped_types = {"loop", "rom", "zram", "ram"}
    skipped_name_prefixes = ("loop", "ram", "zram", "fd", "sr")
    skipped_fstypes = {"squashfs", "tracefs", "debugfs", "cgroup", "cgroup2", "proc", "sysfs", "devtmpfs", "tmpfs"}
    skipped_mount_prefixes = ("/snap", "/var/lib/snapd", "/run", "/dev", "/proc", "/sys")
    for line in lines:
        if not line.strip():
            continue
        try:
            fields = dict(part.split("=", 1) for part in shlex.split(line) if "=" in part)
        except ValueError:
            continue
        name = fields.get("NAME", "").strip()
        device_type = fields.get("TYPE", "").strip()
        fstype = fields.get("FSTYPE", "").strip()
        mountpoint = fields.get("MOUNTPOINT", "").strip()
        if device_type in skipped_types or name.startswith(skipped_name_prefixes):
            continue
        if fstype in skipped_fstypes:
            continue
        if any(mountpoint.startswith(prefix) for prefix in skipped_mount_prefixes):
            continue
        item: dict[str, Any] = {}
        for key, mapped in {
            "NAME": "name",
            "TYPE": "type",
            "MOUNTPOINT": "mountpoint",
            "FSTYPE": "fstype",
            "MODEL": "model",
            "TRAN": "tran",
            "ROTA": "rotational",
            "RM": "removable",
        }.items():
            value = fields.get(key, "").strip()
            if value:
                item[mapped] = value
        size = fields.get("SIZE", "")
        if size.isdigit():
            item["size_bytes"] = int(size)
        if item:
            devices.append(item)
    return devices


def parse_getdevices_script(lines: Iterable[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("| /dev/"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 6:
            continue
        rows.append(
            {
                "device": cells[0],
                "drive_type": cells[1],
                "size": cells[2],
                "power_on": cells[3],
                "logical_volume": cells[4] or "None",
                "mountpoints": cells[5] or "None",
            }
        )
    return rows


def parse_shell_key_values(line: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for token in shlex.split(line):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key] = value
    return values


def parse_readonly_devices(lines: Iterable[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in lines:
        if not line.strip():
            continue
        values = parse_shell_key_values(line)
        name = values.get("device", "")
        if not name:
            continue
        rotational = values.get("rotational", "")
        drive_type = "机械" if rotational == "1" else "固态" if rotational == "0" else "未知"
        rows.append(
            {
                "device": f"/dev/{name}",
                "drive_type": drive_type,
                "size": values.get("size", ""),
                "power_on": "—",
                "logical_volume": values.get("lvm", "").strip(",") or "None",
                "mountpoints": values.get("mountpoints", "").strip(",") or "None",
            }
        )
    return rows


def _first_float(value: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def parse_gpus(gpu_lines: Iterable[str], lspci_lines: Iterable[str]) -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []
    for line in gpu_lines:
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 5:
            gpus.append(
                {
                    "name": parts[0],
                    "memory_total_mib": _first_float(parts[1]),
                    "memory_used_mib": _first_float(parts[2]),
                    "utilization_percent": _first_float(parts[3]),
                    "temperature_c": _first_float(parts[4]),
                }
            )
    if gpus:
        return gpus
    ignored_display_adapters = ("aspeed", "cirrus", "microsoft", "qxl", "virtio", "vmware", "bochs", "matrox")
    real_gpu_markers = ("nvidia", "radeon", "amd/ati", "advanced micro devices")
    for line in lspci_lines:
        lowered = line.lower()
        if any(marker in lowered for marker in ignored_display_adapters):
            continue
        if not any(kind in lowered for kind in ("vga compatible controller", "3d controller", "display controller")):
            continue
        if any(marker in lowered for marker in real_gpu_markers):
            gpus.append({"name": line.strip()})
    return gpus


def split_ips(value: str) -> list[str]:
    return [part for part in re.split(r"[\s,]+", value.strip()) if part]


def is_private_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_private or ip.is_link_local or ip.is_loopback or value.startswith("100.10.")


def primary_ip(ips: Iterable[str], *, prefer_private: bool) -> str:
    values = list(ips)
    if prefer_private:
        for prefix in ("192.168.98.", "172.23.", "172.31.", "10.", "192.168.", "172.", "100.10."):
            for ip in values:
                if ip.startswith(prefix):
                    return ip
        for ip in values:
            if is_private_ip(ip):
                return ip
    for ip in values:
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if parsed.is_global:
            return ip
    return values[0] if values else ""


def connection_ip(target: dict[str, str]) -> str:
    host = target.get("hostname", "").strip()
    if not host:
        return ""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        rows = socket.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return ""
    seen: list[str] = []
    for row in rows:
        ip = cast(str, row[4][0])
        if ip not in seen:
            seen.append(ip)
    for prefix in ("172.", "10.", "192.168."):
        for ip in seen:
            if ip.startswith(prefix):
                return ip
    return seen[0] if seen else ""


def ssh_target(alias: str) -> dict[str, str]:
    completed = subprocess.run(
        ["ssh", "-G", alias],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=True,
        timeout=8,
    )
    target: dict[str, str] = {"alias": alias}
    for line in completed.stdout.splitlines():
        if line.startswith(("hostname ", "user ", "port ")):
            key, value = line.split(None, 1)
            if key in {"hostname", "user", "port"}:
                target[key] = value.strip()
    return target


def resolve_global_ip(hostname: str) -> str:
    try:
        rows = socket.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return ""
    seen: list[str] = []
    for row in rows:
        ip = cast(str, row[4][0])
        if ip not in seen:
            seen.append(ip)
    for ip in seen:
        try:
            if ipaddress.ip_address(ip).is_global:
                return ip
        except ValueError:
            continue
    return seen[0] if seen else ""


def alias_group(alias: str) -> str:
    if alias.endswith(".cube"):
        return "cube"
    if any(marker in alias for marker in PUBLIC_ALIAS_MARKERS):
        return "public"
    return "other"


def connection_kind(alias: str, target: dict[str, str]) -> str:
    host = target.get("hostname", "")
    if alias.endswith(".cube") or is_private_ip(host):
        return "内网连接"
    return "公网连接"


def ssh_config_aliases(path: str | Path | None = None) -> list[str]:
    config_path = Path(path).expanduser() if path else Path.home() / ".ssh/config"
    if not config_path.exists():
        return []
    aliases: list[str] = []
    for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.lower().startswith("host "):
            continue
        for alias in stripped.split()[1:]:
            if not any(char in alias for char in "*?"):
                aliases.append(alias)
    return aliases


def default_candidate_aliases(aliases: Iterable[str] | None = None) -> list[str]:
    values = list(aliases or ssh_config_aliases())
    selected: list[str] = []
    public_exact = {
        "tencent.am",
        "rex.aliyun",
        "rex.newazure",
        "elion.newaliyun",
    }
    for alias in values:
        if alias in EXCLUDED_ALIASES or "lean4web" in alias:
            continue
        if alias.endswith(".cube") or alias in public_exact:
            selected.append(alias)
    return selected


def _alias_preference(alias: str, target: dict[str, str]) -> tuple[int, str]:
    if alias.endswith(".cube"):
        score = 0
    elif alias.startswith("root."):
        score = 4
    else:
        score = 2
    if target.get("user") == "root":
        score += 2
    return (score, alias)


def dedupe_aliases_by_target(aliases: Iterable[str]) -> list[str]:
    by_target: dict[tuple[str, str], tuple[str, dict[str, str]]] = {}
    for alias in aliases:
        try:
            target = ssh_target(alias)
        except Exception:
            target = {"alias": alias, "hostname": alias, "port": "22", "user": ""}
        key = (target.get("hostname", alias), target.get("port", "22"))
        current = by_target.get(key)
        if current is None or _alias_preference(alias, target) < _alias_preference(current[0], current[1]):
            by_target[key] = (alias, target)
    return [alias for alias, _target in sorted(by_target.values(), key=lambda row: _alias_preference(row[0], row[1]))]


def _cpu_from_sections(sections: dict[str, list[str]]) -> dict[str, Any]:
    values = parse_key_values(sections.get("cpu", []))
    cpu: dict[str, Any] = {}
    if values.get("cores", "").isdigit():
        cpu["cores"] = int(values["cores"])
    load = values.get("loadavg", "").split()
    for name, index in (("load1", 0), ("load5", 1), ("load15", 2)):
        if len(load) > index:
            cpu[name] = _first_float(load[index])
    stat1 = [float(x) for x in values.get("stat1", "").split() if re.fullmatch(r"\d+(?:\.\d+)?", x)]
    stat2 = [float(x) for x in values.get("stat2", "").split() if re.fullmatch(r"\d+(?:\.\d+)?", x)]
    if len(stat1) >= 8 and len(stat2) >= 8:
        total1 = sum(stat1)
        total2 = sum(stat2)
        idle_delta = (stat2[3] + stat2[4]) - (stat1[3] + stat1[4])
        total_delta = total2 - total1
        if total_delta > 0:
            cpu["usage_percent"] = (total_delta - idle_delta) * 100 / total_delta
    return cpu


def _memory_from_sections(sections: dict[str, list[str]]) -> dict[str, Any]:
    mem = parse_meminfo(sections.get("meminfo", []))
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable") or (mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0))
    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_percent": ((total - available) / total * 100) if total else None,
        "swap_total_bytes": swap_total,
        "swap_used_bytes": max(swap_total - swap_free, 0),
    }


def parse_probe_output(alias: str, output: str, target: dict[str, str]) -> dict[str, Any]:
    sections = parse_sections(output)
    meta = parse_key_values(sections.get("meta", []))
    group = alias_group(alias)
    kind = connection_kind(alias, target)
    ips = split_ips(meta.get("ips", ""))
    display_ip = connection_ip(target)
    if not display_ip:
        display_ip = primary_ip(ips, prefer_private=(kind == "内网连接"))
    prefer_private = kind == "内网连接"
    if not display_ip and kind == "公网连接":
        display_ip = resolve_global_ip(target.get("hostname", alias))
    getdevices_script = parse_getdevices_script(sections.get("getdevices_script", []))
    getdevices = getdevices_script or parse_readonly_devices(sections.get("readonly_devices", []))
    return {
        "alias": alias,
        "display_name": meta.get("hostname") or alias,
        "group": group,
        "connection_kind": kind,
        "ip": display_ip,
        "status": "online",
        "hostname": meta.get("hostname", ""),
        "user": meta.get("user", ""),
        "kernel": meta.get("kernel", ""),
        "collected_at": meta.get("collected_at") or utc_now(),
        "cpu": _cpu_from_sections(sections),
        "memory": _memory_from_sections(sections),
        "disks": parse_df(sections.get("df", [])),
        "devices": parse_lsblk(sections.get("lsblk", [])),
        "getdevices": getdevices,
        "gpus": parse_gpus(sections.get("gpu", []), sections.get("lspci", [])),
    }


def probe_alias(alias: str, *, timeout: int = 18) -> dict[str, Any]:
    try:
        target = ssh_target(alias)
    except Exception:
        target = {"alias": alias, "hostname": alias, "port": "22", "user": ""}
    kind = connection_kind(alias, target)
    fallback_ip = connection_ip(target) or (resolve_global_ip(target.get("hostname", alias)) if kind == "公网连接" else target.get("hostname", ""))
    try:
        completed = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", alias, "bash -s"],
            input=REMOTE_PROBE_SCRIPT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "alias": alias,
            "display_name": alias,
            "group": alias_group(alias),
            "connection_kind": kind,
            "ip": fallback_ip,
            "status": "unreachable",
            "error": "timeout",
            "collected_at": utc_now(),
        }
    if completed.returncode != 0:
        message = " | ".join((completed.stderr or completed.stdout).strip().splitlines()[:2])
        return {
            "alias": alias,
            "display_name": alias,
            "group": alias_group(alias),
            "connection_kind": kind,
            "ip": fallback_ip,
            "status": "unreachable",
            "error": message or f"ssh exit {completed.returncode}",
            "collected_at": utc_now(),
        }
    return parse_probe_output(alias, completed.stdout, target)


def collect_server_status(aliases: Iterable[str], *, timeout: int = 18, workers: int = 8) -> dict[str, Any]:
    selected = dedupe_aliases_by_target(aliases)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_map = {pool.submit(probe_alias, alias, timeout=timeout): alias for alias in selected}
        for future in as_completed(future_map):
            results.append(future.result())
    order = {"cube": 0, "public": 1, "other": 2}
    results.sort(key=lambda item: (order.get(text_value(item.get("group"), "other"), 9), text_value(item.get("display_name") or item.get("alias"), "")))
    online = sum(1 for item in results if item.get("status") == "online")
    return {"generated_at": utc_now(), "count": len(results), "online": online, "servers": results}


def _status_label(status: str) -> str:
    return {"online": "在线", "unreachable": "不可达", "error": "错误"}.get(status, status or "未知")


def _gpu_summary(gpus: list[dict[str, Any]]) -> str:
    if not gpus:
        return "NULL"
    names = [text_value(gpu.get("name"), "GPU") for gpu in gpus]
    unique_names = []
    for name in names:
        if name not in unique_names:
            unique_names.append(name)
    util_values = []
    for gpu in gpus:
        value = gpu.get("utilization_percent")
        if value is None:
            continue
        try:
            util_values.append(float(value))
        except (TypeError, ValueError):
            continue
    max_util = max(util_values) if util_values else None
    suffix = f" · max {max_util:.0f}%" if max_util is not None else ""
    return f"{len(gpus)} GPU · {', '.join(unique_names[:2])}{'…' if len(unique_names) > 2 else ''}{suffix}"


def _gpu_table(gpus: list[dict[str, Any]]) -> str:
    rows = []
    for gpu in gpus:
        total = gpu.get("memory_total_mib")
        used = gpu.get("memory_used_mib")
        memory = f"{used or 0:.0f}/{total:.0f} MiB" if total is not None else "—"
        rows.append(
            "<tr>"
            f"<td>{html_text(gpu.get('name'), 'GPU')}</td>"
            f"<td>{html_text(memory)}</td>"
            f"<td>{html_text(format_percent(gpu.get('utilization_percent')))}</td>"
            f"<td>{html_text(gpu.get('temperature_c'))}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="4">GPU: NULL</td></tr>'
    return "<table><thead><tr><th>GPU</th><th>显存</th><th>利用率</th><th>温度 °C</th></tr></thead><tbody>" + body + "</tbody></table>"


def _disk_table(disks: list[dict[str, Any]]) -> str:
    rows = []
    for disk in disks:
        rows.append(
            "<tr>"
            f"<td>{html_text(disk.get('mountpoint'))}</td>"
            f"<td>{html_text(disk.get('filesystem'))}</td>"
            f"<td>{html_text(disk.get('type'))}</td>"
            f"<td>{html_text(format_bytes(disk.get('size_bytes')))}</td>"
            f"<td>{html_text(format_bytes(disk.get('used_bytes')))}</td>"
            f"<td>{html_text(format_bytes(disk.get('available_bytes')))}</td>"
            f"<td>{html_text(format_percent(disk.get('used_percent')))}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="7">暂无挂载目录数据</td></tr>'
    return "<table><thead><tr><th>挂载点</th><th>设备</th><th>类型</th><th>总量</th><th>已用</th><th>可用</th><th>占用</th></tr></thead><tbody>" + body + "</tbody></table>"


def _device_table(devices: list[dict[str, Any]]) -> str:
    rows = []
    for device in devices:
        rows.append(
            "<tr>"
            f"<td>{html_text(device.get('name'))}</td>"
            f"<td>{html_text(device.get('type'))}</td>"
            f"<td>{html_text(format_bytes(device.get('size_bytes')))}</td>"
            f"<td>{html_text(device.get('mountpoint'))}</td>"
            f"<td>{html_text(device.get('fstype'))}</td>"
            f"<td>{html_text(device.get('model'))}</td>"
            f"<td>{html_text(device.get('tran'))}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="7">暂无 devices 数据</td></tr>'
    return "<table><thead><tr><th>名称</th><th>类型</th><th>大小</th><th>挂载点</th><th>文件系统</th><th>型号</th><th>总线</th></tr></thead><tbody>" + body + "</tbody></table>"


def _getdevices_table(rows_data: list[dict[str, str]]) -> str:
    rows = []
    for item in rows_data:
        rows.append(
            "<tr>"
            f"<td>{html_text(item.get('device'))}</td>"
            f"<td>{html_text(item.get('drive_type'))}</td>"
            f"<td>{html_text(item.get('size'))}</td>"
            f"<td>{html_text(item.get('power_on'))}</td>"
            f"<td>{html_text(item.get('logical_volume'))}</td>"
            f"<td>{html_text(item.get('mountpoints'))}</td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="6">暂无 getdevices 摘要</td></tr>'
    return "<table><thead><tr><th>硬盘设备</th><th>类型</th><th>容量</th><th>使用时间</th><th>逻辑卷</th><th>挂载目录</th></tr></thead><tbody>" + body + "</tbody></table>"


def _server_card(server: dict[str, Any]) -> str:
    cpu = cast(dict[str, Any], server.get("cpu")) if isinstance(server.get("cpu"), dict) else {}
    memory = cast(dict[str, Any], server.get("memory")) if isinstance(server.get("memory"), dict) else {}
    disks = cast(list[dict[str, Any]], server.get("disks")) if isinstance(server.get("disks"), list) else []
    devices = cast(list[dict[str, Any]], server.get("devices")) if isinstance(server.get("devices"), list) else []
    getdevices = cast(list[dict[str, str]], server.get("getdevices")) if isinstance(server.get("getdevices"), list) else []
    gpus = cast(list[dict[str, Any]], server.get("gpus")) if isinstance(server.get("gpus"), list) else []
    primary_disk = next((disk for disk in disks if disk.get("mountpoint") == "/"), disks[0] if disks else {})
    error_html = f'<div class="server-error">{html_text(server.get("error"))}</div>' if server.get("error") else ""
    return f"""
<div class="server-card status-{html_text(server.get('status'), 'unknown')}">
  <div class="server-card-head">
    <div>
      <div class="server-title">{html_text(server.get('display_name') or server.get('alias'))}</div>
      <div class="server-subtitle">{html_text(server.get('alias'))} · {html_text(server.get('connection_kind'))} · {html_text(server.get('collected_at'))}</div>
    </div>
    <span class="server-pill">{html_text(_status_label(text_value(server.get('status'), 'unknown')))}</span>
  </div>
  {error_html}
  <div class="metric-grid">
    <div><span>IP</span><strong>{html_text(server.get('ip'))}</strong></div>
    <div><span>CPU</span><strong>{html_text(format_percent(cpu.get('usage_percent')))} · {html_text(cpu.get('cores'))} cores · load {html_text(cpu.get('load1'))}</strong></div>
    <div><span>内存</span><strong>{html_text(format_percent(memory.get('used_percent')))} · {html_text(format_bytes(memory.get('available_bytes')))} 可用 / {html_text(format_bytes(memory.get('total_bytes')))}</strong></div>
    <div><span>硬盘</span><strong>{html_text(primary_disk.get('mountpoint'))} {html_text(format_percent(primary_disk.get('used_percent')))} · {html_text(format_bytes(primary_disk.get('available_bytes')))} 可用</strong></div>
    <div><span>GPU</span><strong>{html_text(_gpu_summary(gpus))}</strong></div>
  </div>
  <details>
    <summary>展开 GPU、挂载目录和 devices</summary>
    <div class="detail-section"><h4>GPU 详情</h4>{_gpu_table(gpus)}</div>
    <div class="detail-section"><h4>挂载目录容量</h4>{_disk_table(disks)}</div>
    <div class="detail-section"><h4>getdevices 摘要</h4>{_getdevices_table(getdevices)}</div>
    <div class="detail-section"><h4>lsblk devices</h4>{_device_table(devices)}</div>
    <div class="detail-section"><h4>系统</h4><p>hostname={html_text(server.get('hostname'))} · user={html_text(server.get('user'))} · kernel={html_text(server.get('kernel'))}</p></div>
  </details>
</div>
"""


def render_servers_html(data: dict[str, Any]) -> str:
    servers = [item for item in data.get("servers", []) if isinstance(item, dict)]
    generated_at = html_text(data.get("generated_at"))
    online = sum(1 for item in servers if item.get("status") == "online")
    cards = "\n".join(_server_card(item) for item in servers)
    return f"""
<style>
.server-summary {{ margin-bottom: 0.8rem; color: var(--color-text-subdue); }}
.server-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 0.75rem; }}
.server-card {{ border: 1px solid var(--color-separator); border-radius: 14px; padding: 0.8rem; background: var(--color-widget-background); }}
.server-card-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 0.75rem; margin-bottom: 0.65rem; }}
.server-title {{ font-weight: 700; font-size: 1.08rem; }}
.server-subtitle {{ color: var(--color-text-subdue); font-size: 0.78rem; margin-top: 0.15rem; }}
.server-pill {{ border: 1px solid var(--color-separator); border-radius: 999px; padding: 0.12rem 0.5rem; font-size: 0.78rem; white-space: nowrap; }}
.status-online .server-pill {{ color: var(--color-positive); }}
.status-unreachable .server-pill, .status-error .server-pill {{ color: var(--color-negative); }}
.server-error {{ color: var(--color-negative); margin-bottom: 0.55rem; }}
.metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 0.55rem; }}
.metric-grid div {{ border: 1px solid var(--color-separator); border-radius: 10px; padding: 0.5rem; min-width: 0; }}
.metric-grid span {{ display: block; color: var(--color-text-subdue); font-size: 0.75rem; margin-bottom: 0.25rem; }}
.metric-grid strong {{ font-size: 0.88rem; overflow-wrap: anywhere; }}
.server-card details {{ margin-top: 0.7rem; }}
.server-card summary {{ cursor: pointer; color: var(--color-primary); }}
.detail-section {{ margin-top: 0.65rem; overflow-x: auto; }}
.detail-section h4 {{ margin: 0.2rem 0 0.35rem; }}
.detail-section table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
.detail-section th, .detail-section td {{ border-bottom: 1px solid var(--color-separator); padding: 0.28rem 0.35rem; text-align: left; vertical-align: top; }}
</style>
<div class="server-summary">最新采集：{generated_at} · 服务器 {len(servers)} 台 · 在线 {online} 台 · 数据来自静态 JSON 快照</div>
<div class="server-grid">
{cards or '<p>暂无服务器状态数据。</p>'}
</div>
"""


def build_servers_page(data: dict[str, Any], *, page_name: str = SERVER_PAGE_NAME) -> dict[str, Any]:
    return {
        "name": page_name,
        "slug": "servers",
        "width": "wide",
        "columns": [
            {
                "size": "full",
                "widgets": [
                    {
                        "type": "html",
                        "title": "服务器状态",
                        "source": render_servers_html(data),
                    }
                ],
            }
        ],
    }


def replace_servers_page(config: dict[str, Any], data: dict[str, Any], *, page_name: str = SERVER_PAGE_NAME) -> dict[str, Any]:
    updated = deepcopy(config)
    pages = updated.setdefault("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Glance config `pages` must be a list")
    legacy_names = set(LEGACY_SERVER_PAGE_NAMES) | {page_name}
    pages[:] = [page for page in pages if not (isinstance(page, dict) and page.get("name") in legacy_names)]
    pages.append(build_servers_page(data, page_name=page_name))
    return updated
