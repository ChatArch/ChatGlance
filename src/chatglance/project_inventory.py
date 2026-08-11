"""Read-only ChatArch repository inventory refresh helpers."""

from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import re
import subprocess
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 CI
    import tomli as tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from chatglance.projects import category_key, display_category

JsonDict = dict[str, Any]
FetchText = Callable[[str, str], str | None]
FetchJson = Callable[[str], Any | None]
ActualCliTreeFetcher = Callable[[str, str, int], str | None]

GITHUB_API = "https://api.github.com"
PYPI_API = "https://pypi.org/pypi"
DEFAULT_TIMEOUT = 12


@dataclass(frozen=True)
class RefreshOptions:
    """Options for read-only project inventory refresh."""

    owner: str = "ChatArch"
    limit: int = 500
    workers: int = 12
    timeout: int = DEFAULT_TIMEOUT
    cli_tree_timeout: int = 90
    collect_actual_cli_trees: bool = False
    uvx_bin: str = "uvx"
    token_env: tuple[str, ...] = ("CHATGLANCE_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")
    chatgh_bin: str = "chatgh"
    generated_at: str | None = None


def beijing_now_iso() -> str:
    """Return the current time in Beijing time for dashboard snapshots."""

    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0).isoformat()


def _token_from_extraheader(header: str) -> str | None:
    redacted_prefix = "Authorization: *** "
    basic_prefix = "Authorization: Basic "
    if header.startswith(redacted_prefix):
        encoded = header[len(redacted_prefix) :].strip()
    elif header.startswith(basic_prefix) or header.lower().startswith(basic_prefix.lower()):
        encoded = header[len(basic_prefix) :].strip()
    else:
        return None
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except Exception:
        return None
    username, sep, password = decoded.partition(":")
    if sep != ":" or username != "x-access-token" or not password:
        return None
    return password


def read_token_from_repo_git_config() -> str | None:
    """Read a repo-local GitHub extraHeader token without logging it.

    ChatGH stores repo-scoped HTTPS tokens as local git extraHeader values. Reuse
    that credential when the refresh script is run from a ChatArch checkout so
    private repositories such as ChatGlance can be inspected without requiring a
    separately exported environment variable.
    """

    try:
        result = subprocess.run(
            ["git", "config", "--local", "--get-regexp", r"^http\..*github\.com.*\.[eE]xtra[hH]eader$"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        _key, sep, value = line.partition(" ")
        if not sep:
            continue
        token = _token_from_extraheader(value.strip())
        if token:
            return token
    return None


def resolve_token(env_names: Sequence[str] = ("CHATGLANCE_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")) -> str | None:
    """Resolve an optional GitHub token without logging it."""

    for name in env_names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return read_token_from_repo_git_config()


def run_chatgh_repo_list(*, owner: str, limit: int, chatgh_bin: str = "chatgh") -> list[JsonDict]:
    """Return repositories from ChatGH's authenticated repo-list command."""

    result = subprocess.run(
        [chatgh_bin, "repo", "list", "--owner", owner, "--limit", str(limit), "--sort", "name", "--direction", "asc", "--json-output"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise ValueError("chatgh repo list --json-output must return a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def load_repo_rows(path: str | Path) -> list[JsonDict]:
    """Load repository rows from a ChatGH JSON array or an inventory object."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("repositories"), list):
        payload = payload["repositories"]
    if not isinstance(payload, list):
        raise ValueError("repo list JSON must be an array or an object with repositories")
    return [item for item in payload if isinstance(item, dict)]


def _request_json(url: str, *, token: str | None, timeout: int) -> Any | None:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ChatGlance-inventory-refresh"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _request_raw(url: str, *, token: str | None, timeout: int) -> str | None:
    headers = {"User-Agent": "ChatGlance-inventory-refresh"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None


def make_github_fetcher(*, token: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> FetchText:
    """Return a fetcher for default-branch repository files.

    When a token is available, use the GitHub Contents API to raise rate limits and
    support private repositories the token can read. Otherwise fall back to public
    raw.githubusercontent.com URLs.
    """

    def fetch(item_name: str, rel_path: str) -> str | None:
        owner_repo = item_name.strip("/")
        if "/" not in owner_repo:
            owner_repo = f"ChatArch/{owner_repo}"
        owner, repo = owner_repo.split("/", 1)
        encoded = "/".join(urllib.parse.quote(part) for part in rel_path.strip("/").split("/"))
        if token:
            api_url = f"{GITHUB_API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/contents/{encoded}"
            payload = _request_json(api_url, token=token, timeout=timeout)
            if isinstance(payload, dict):
                if payload.get("encoding") == "base64" and isinstance(payload.get("content"), str):
                    try:
                        return base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
                    except Exception:
                        return None
                if isinstance(payload.get("content"), str):
                    return payload["content"]
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{encoded}"
        return _request_raw(raw_url, token=token, timeout=timeout)

    return fetch


def make_pypi_fetcher(*, timeout: int = DEFAULT_TIMEOUT) -> FetchJson:
    """Return a read-only PyPI JSON fetcher for package version display.

    The project dashboard intentionally uses PyPI as the only version source so
    Git tags, GitHub releases, and local manifests cannot make the page disagree
    with the published package state.
    """

    def fetch(package_name: str) -> Any | None:
        name = str(package_name or "").strip()
        if not name:
            return None
        encoded = urllib.parse.quote(name, safe="")
        request = urllib.request.Request(
            f"{PYPI_API}/{encoded}/json",
            headers={"Accept": "application/json", "User-Agent": "ChatGlance-inventory-refresh"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    return None
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return None

    return fetch


def pypi_version(package_name: str | None, *, fetcher: FetchJson) -> JsonDict:
    """Return a PyPI-only version object for display."""

    if not package_name:
        return {"value": None, "source": None}
    payload = fetcher(package_name)
    if not isinstance(payload, dict):
        return {"value": None, "source": None}
    info = payload.get("info")
    if not isinstance(info, dict):
        return {"value": None, "source": None}
    version = str(info.get("version") or "").strip()
    if not version:
        return {"value": None, "source": None}
    return {"value": version, "source": "pypi"}


def _first_string_arg(call_args: str) -> str | None:
    match = re.search(r"(?:^|[,(]\s*)(?:name\s*=\s*)?['\"]([^'\"]+)['\"]", call_args)
    return match.group(1) if match else None


def _next_function_name(lines: list[str], start_index: int) -> str | None:
    for line in lines[start_index + 1 : start_index + 8]:
        match = re.match(r"\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if match:
            return match.group(1).replace("_", "-")
    return None


def parse_click_command_names(source: str) -> list[str]:
    """Extract Click command/group names from source without executing it."""

    names: list[str] = []
    lines = source.splitlines()
    decorator = re.compile(r"^\s*@(?P<receiver>[A-Za-z_][\w]*)\.(?P<kind>command|group)\((?P<args>[^)]*)\)")
    for index, line in enumerate(lines):
        match = decorator.match(line)
        if not match:
            continue
        receiver = match.group("receiver")
        kind = match.group("kind")
        args = match.group("args")
        # The entrypoint/root Click group itself is not a subcommand of the CLI.
        if receiver == "click" and kind == "group":
            continue
        name = _first_string_arg(args) or _next_function_name(lines, index)
        if name and name not in names:
            names.append(name)
    return names


def _as_dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def baseline_repositories(data: JsonDict | None) -> dict[str, JsonDict]:
    """Return a name-indexed map of prior inventory rows used as review baseline."""

    if not isinstance(data, dict):
        return {}
    rows = data.get("repositories")
    if not isinstance(rows, list):
        return {}
    result: dict[str, JsonDict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip().lower()
        if name:
            result[name] = row
    return result


def load_baseline_inventory(path: str | Path | None) -> JsonDict | None:
    """Load an optional prior inventory used to preserve reviewed categories."""

    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("baseline inventory JSON must be an object")
    return payload


def _script_entry_modules(pyproject: JsonDict) -> dict[str, str]:
    scripts: dict[str, str] = {}
    project = _as_dict(pyproject.get("project"))
    for table in (project.get("scripts"), project.get("gui-scripts")):
        if isinstance(table, dict):
            scripts.update({str(key): str(value) for key, value in table.items()})
    tool = _as_dict(pyproject.get("tool"))
    poetry = _as_dict(tool.get("poetry"))
    poetry_scripts = poetry.get("scripts")
    if isinstance(poetry_scripts, dict):
        scripts.update({str(key): str(value) for key, value in poetry_scripts.items()})
    return scripts


def _module_to_path(entrypoint: str) -> str | None:
    module = entrypoint.split(":", 1)[0].strip()
    if not module:
        return None
    return "src/" + "/".join(module.split(".")) + ".py"


def parse_python_project_cli(pyproject: JsonDict, *, fetch_file: Callable[[str], str | None] | None = None) -> JsonDict:
    """Extract Python package entrypoint names only.

    The project page tracks whether a repository exposes a package-level CLI
    entrypoint. It must not expand Click/Typer subcommands into the table, because
    subcommands are command surface details rather than project identity.
    """

    scripts = _script_entry_modules(pyproject)
    commands = list(scripts.keys())
    return {
        "commands": commands,
        "sources": ["pyproject.scripts"] if scripts else [],
        "tree_status": "entrypoint-only" if commands else "not-detected",
    }


TREE_NODE_RE = re.compile(r"(?:├──|└──)\s+(.+)$")


def _tree_token(text: str) -> str:
    before_comment = text.split("#", 1)[0].strip()
    parts = before_comment.split()
    return parts[0].strip() if parts else ""


def parse_actual_cli_tree_output(output: str) -> JsonDict:
    """Parse a ChatArch-style ``--tree`` output into business command counts.

    The dashboard classification uses real installed CLI trees. Global options
    such as ``--help``/``--version``/``--tree`` are not business commands; every
    non-option tree node is counted as a substantive CLI command node.
    """

    business_commands: list[str] = []
    global_options: list[str] = []
    for line in output.splitlines():
        match = TREE_NODE_RE.search(line)
        if not match:
            continue
        token = _tree_token(match.group(1))
        if not token:
            continue
        if token.startswith("-"):
            if token not in global_options:
                global_options.append(token)
            continue
        business_commands.append(token)
    if not business_commands:
        in_commands = False
        for raw_line in output.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                if in_commands:
                    break
                continue
            if stripped.rstrip(":").lower() == "commands":
                in_commands = True
                continue
            if not in_commands:
                continue
            if raw_line[:1] and not raw_line.startswith((" ", "\t")):
                break
            token = stripped.split()[0] if stripped.split() else ""
            if token and not token.startswith("-") and token not in business_commands:
                business_commands.append(token)
    return {
        "status": "ok",
        "business_commands": business_commands,
        "business_command_count": len(business_commands),
        "global_options": global_options,
        "global_option_count": len(global_options),
    }


def make_actual_cli_tree_fetcher(*, uvx_bin: str = "uvx") -> ActualCliTreeFetcher:
    """Return a fetcher that installs the latest PyPI package and reads CLI tree.

    ``uvx --from <package>@latest`` makes the refresh classify the currently
    published PyPI package instead of a stale local checkout or cached tool.
    """

    def fetch(package_name: str, command: str, timeout: int) -> str | None:
        package = str(package_name or "").strip()
        entrypoint = str(command or "").strip()
        if not package or not entrypoint:
            return None
        package_spec = f"{package}@latest"
        base = [uvx_bin, "--from", package_spec, entrypoint]
        for args in ([*base, "--tree"], [*base, "--help"]):
            try:
                result = subprocess.run(
                    args,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0 and result.stdout:
                return result.stdout
        return None

    return fetch


def enrich_actual_cli_tree(item: JsonDict, *, fetcher: ActualCliTreeFetcher, timeout: int) -> None:
    """Add actual installed CLI tree evidence to an enriched inventory row."""

    package = _as_dict(item.get("package"))
    cli = dict(_as_dict(item.get("cli")))
    package_name = str(package.get("python_name") or item.get("name") or "").strip()
    commands = [str(command).strip() for command in cli.get("commands", []) if str(command).strip()]
    if not package_name or not commands:
        cli["actual_tree"] = {"status": "no-entrypoint", "business_commands": [], "business_command_count": 0, "global_options": [], "global_option_count": 0}
        item["cli"] = cli
        return

    per_entrypoint: dict[str, JsonDict] = {}
    all_business: list[str] = []
    all_options: list[str] = []
    statuses: list[str] = []
    for command in commands:
        output = fetcher(package_name, command, timeout)
        if not output:
            tree = {"status": "unavailable", "business_commands": [], "business_command_count": 0, "global_options": [], "global_option_count": 0}
        else:
            tree = parse_actual_cli_tree_output(output)
        per_entrypoint[command] = tree
        statuses.append(str(tree.get("status") or "unknown"))
        all_business.extend(str(cmd) for cmd in tree.get("business_commands", []) if str(cmd).strip())
        for option in tree.get("global_options", []):
            text = str(option).strip()
            if text and text not in all_options:
                all_options.append(text)

    if any(status == "ok" for status in statuses):
        status = "ok"
    elif statuses:
        status = statuses[0]
    else:
        status = "no-entrypoint"
    cli["actual_tree"] = {
        "status": status,
        "business_commands": all_business,
        "business_command_count": len(all_business),
        "global_options": all_options,
        "global_option_count": len(all_options),
        "entrypoints": per_entrypoint,
    }
    item["cli"] = cli


def enrich_repository(
    row: JsonDict,
    *,
    owner: str,
    fetcher: FetchText,
    pypi_fetcher: FetchJson,
    baseline_item: JsonDict | None = None,
    actual_cli_tree_fetcher: ActualCliTreeFetcher | None = None,
    cli_tree_timeout: int = 90,
) -> JsonDict:
    """Enrich a ChatGH repo row with lightweight manifest and CLI evidence."""

    item = dict(row)
    name = str(item.get("name") or "").strip()
    full_name = str(item.get("full_name") or f"{owner}/{name}")
    evidence: JsonDict = dict(_as_dict(item.get("evidence")))
    package: JsonDict = dict(_as_dict(item.get("package"))) or {"python_name": None, "npm_name": None}
    item.setdefault("docs", [{"url": f"https://arch.gh.wzhecnu.cn/{name}/", "source": "chatarch-pages-candidate"}] if name else [])
    item.setdefault("version", {"value": None, "source": None})
    item.setdefault("cli", {"commands": [], "sources": [], "tree_status": "not-detected"})

    pyproject_text = fetcher(full_name, "pyproject.toml") if name else None
    if pyproject_text:
        try:
            pyproject = tomllib.loads(pyproject_text)
        except tomllib.TOMLDecodeError:
            pyproject = {}
        project = _as_dict(pyproject.get("project"))
        item["category"] = "python-package"
        item["language"] = item.get("language") or "Python"
        if project.get("description"):
            item["description"] = project["description"]
        package["python_name"] = project.get("name") or package.get("python_name") or name
        package.setdefault("npm_name", None)
        item["version"] = pypi_version(str(package.get("python_name") or name), fetcher=pypi_fetcher)
        item["cli"] = parse_python_project_cli(pyproject)
        evidence.update({"has_pyproject": True, "details_source": "chatgh+github-contents"})
    else:
        package_json_text = fetcher(full_name, "package.json") if name else None
        if package_json_text:
            try:
                package_json = json.loads(package_json_text)
            except json.JSONDecodeError:
                package_json = {}
            if isinstance(package_json, dict):
                item["category"] = "node-package"
                if package_json.get("description"):
                    item["description"] = package_json["description"]
                package["npm_name"] = package_json.get("name") or package.get("npm_name")
                package.setdefault("python_name", None)
                item["version"] = {"value": None, "source": None}
                bin_field = package_json.get("bin")
                if isinstance(bin_field, dict):
                    commands = sorted(str(command) for command in bin_field)
                elif isinstance(bin_field, str) and package_json.get("name"):
                    commands = [str(package_json["name"]).split("/")[-1]]
                else:
                    commands = []
                item["cli"] = {"commands": commands, "sources": ["package.json.bin"] if commands else [], "tree_status": "command-names-only" if commands else "not-detected"}
                evidence.update({"has_package_json": True, "details_source": "chatgh+github-contents"})

    baseline = _as_dict(baseline_item)
    baseline_category = str(baseline.get("category") or "").strip()
    if baseline_category:
        item["reviewed_category"] = baseline_category
        item["category"] = baseline_category

    item["package"] = package
    if actual_cli_tree_fetcher and package.get("python_name"):
        enrich_actual_cli_tree(item, fetcher=actual_cli_tree_fetcher, timeout=cli_tree_timeout)
    item["evidence"] = evidence
    item["category"] = category_key(item)
    item["category_label"] = display_category(item)
    return item


def build_project_inventory(
    repo_rows: Iterable[JsonDict],
    *,
    owner: str = "ChatArch",
    generated_at: str | None = None,
    fetcher: FetchText | None = None,
    pypi_fetcher: FetchJson | None = None,
    actual_cli_tree_fetcher: ActualCliTreeFetcher | None = None,
    cli_tree_timeout: int = 90,
    baseline_inventory: JsonDict | None = None,
    workers: int = 12,
) -> JsonDict:
    """Build the dashboard inventory object from repository rows."""

    rows = [row for row in repo_rows if isinstance(row, dict)]
    fetcher = fetcher or make_github_fetcher()
    pypi_fetcher = pypi_fetcher or make_pypi_fetcher()
    baseline = baseline_repositories(baseline_inventory)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        repositories = list(
            executor.map(
                lambda row: enrich_repository(
                    row,
                    owner=owner,
                    fetcher=fetcher,
                    pypi_fetcher=pypi_fetcher,
                    baseline_item=baseline.get(str(row.get("name") or "").strip().lower()),
                    actual_cli_tree_fetcher=actual_cli_tree_fetcher,
                    cli_tree_timeout=cli_tree_timeout,
                ),
                rows,
            )
        )

    counts = {
        "visible_repos": len(repositories),
        "public": sum(1 for item in repositories if not item.get("private")),
        "private": sum(1 for item in repositories if item.get("private")),
        "archived": sum(1 for item in repositories if item.get("archived")),
        "with_open_prs": sum(1 for item in repositories if int(item.get("open_prs") or 0) > 0),
        "with_open_issues": sum(1 for item in repositories if int(item.get("open_issues") or 0) > 0),
        "total_open_prs": sum(int(item.get("open_prs") or 0) for item in repositories),
        "total_open_issues": sum(int(item.get("open_issues") or 0) for item in repositories),
        "with_detected_version": sum(1 for item in repositories if isinstance(item.get("version"), dict) and bool(item["version"].get("value"))),
        "with_detected_cli_entries": sum(1 for item in repositories if isinstance(item.get("cli"), dict) and bool(item["cli"].get("commands"))),
        "with_detected_cli_commands": sum(1 for item in repositories if isinstance(item.get("cli"), dict) and bool(item["cli"].get("commands"))),
        "with_actual_cli_tree": sum(1 for item in repositories if isinstance(item.get("cli"), dict) and isinstance(item["cli"].get("actual_tree"), dict) and item["cli"]["actual_tree"].get("status") == "ok"),
        "with_actual_cli_business_commands": sum(1 for item in repositories if isinstance(item.get("cli"), dict) and isinstance(item["cli"].get("actual_tree"), dict) and int(item["cli"]["actual_tree"].get("business_command_count") or 0) > 0),
        "with_docs_candidates": sum(1 for item in repositories if item.get("docs")),
    }
    categories: dict[str, int] = {}
    for item in repositories:
        key = category_key(item)
        categories[key] = categories.get(key, 0) + 1
    return {
        "generated_at": generated_at or beijing_now_iso(),
        "source": {
            "owner": owner,
            "repo_count": len(rows),
            "auth_source": "chatgh repo list + optional GitHub token environment",
            "notes": "Repository list comes from ChatGH. Manifest and package entrypoint evidence is fetched read-only from default-branch repository files. Version display uses PyPI only. When enabled, actual CLI tree evidence comes from installing the latest PyPI package with uvx and running each entrypoint's --tree/help output. Credentials are omitted.",
        },
        "counts": counts,
        "categories": categories,
        "repositories": repositories,
    }


def refresh_project_inventory(*, output_path: str | Path, options: RefreshOptions = RefreshOptions(), repo_list_json: str | Path | None = None, baseline_data: str | Path | None = None) -> JsonDict:
    """Refresh and write the project inventory JSON."""

    rows = load_repo_rows(repo_list_json) if repo_list_json else run_chatgh_repo_list(owner=options.owner, limit=options.limit, chatgh_bin=options.chatgh_bin)
    token = resolve_token(options.token_env)
    fetcher = make_github_fetcher(token=token, timeout=options.timeout)
    baseline_inventory = load_baseline_inventory(baseline_data)
    actual_cli_tree_fetcher = make_actual_cli_tree_fetcher(uvx_bin=options.uvx_bin) if options.collect_actual_cli_trees else None
    inventory = build_project_inventory(
        rows,
        owner=options.owner,
        generated_at=options.generated_at,
        fetcher=fetcher,
        baseline_inventory=baseline_inventory,
        workers=options.workers,
        actual_cli_tree_fetcher=actual_cli_tree_fetcher,
        cli_tree_timeout=options.cli_tree_timeout,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return inventory
