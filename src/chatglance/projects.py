"""Build Glance project-dashboard pages from ChatArch repository inventory JSON."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

PAGE_NAME = "项目"
LEGACY_PAGE_NAMES = {"Projects", "ChatArch Projects", "ChatArch Projects List"}

CATEGORY_LABELS = {
    "python-package": "Python 包",
    "python-early": "Python (early)",
    "node-package": "Node / npm 包",
    "service/app": "服务 / 应用",
    "docs/site": "文档 / 站点",
    "other": "其他项目",
}
CATEGORY_ORDER = ["python-package", "node-package", "service/app", "docs/site", "other", "python-early"]
CATEGORY_ALIASES = {
    "python-package": "python-package",
    "python-early": "python-early",
    "node/npm-package": "node-package",
    "node-package": "node-package",
    "docs-site": "docs/site",
    "docs/site": "docs/site",
    "service/app": "service/app",
    "project/unknown": "other",
    "other": "other",
}
EARLY_PYTHON_CATEGORY_ALIASES = {"python-package-template/early", "template/early", "python-early"}


def load_inventory(path: str | Path) -> dict[str, Any]:
    """Load a ChatArch repository inventory JSON file."""

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("inventory JSON must be an object")
    repos = data.get("repositories")
    if not isinstance(repos, list):
        raise ValueError("inventory JSON must contain a repositories list")
    return data


def safe_date(value: Any) -> str:
    text = str(value or "").strip()
    if "T" in text:
        return text.split("T", 1)[0]
    return text or "—"


def text_value(value: Any, fallback: str = "—") -> str:
    text = str(value or "").strip()
    return text or fallback


def html_text(value: Any, fallback: str = "—") -> str:
    return html.escape(text_value(value, fallback), quote=True)


def _raw_category(value: Any) -> str:
    return text_value(value, "other").strip().lower()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _cli_commands(item: dict[str, Any]) -> list[str]:
    cli = _mapping(item.get("cli"))
    raw_commands = cli.get("commands")
    commands = raw_commands if isinstance(raw_commands, list) else []
    return [str(command).strip() for command in commands if str(command).strip()]


def _actual_cli_tree(item: dict[str, Any]) -> dict[str, Any]:
    cli = _mapping(item.get("cli"))
    return _mapping(cli.get("actual_tree"))


def _actual_business_command_count(item: dict[str, Any]) -> int | None:
    tree = _actual_cli_tree(item)
    if text_value(tree.get("status"), "") != "ok":
        return None
    try:
        return int(tree.get("business_command_count") or 0)
    except (TypeError, ValueError):
        return 0


def _actual_tree_status(item: dict[str, Any]) -> str:
    return text_value(_actual_cli_tree(item).get("status"), "")


def _description_is_placeholder(item: dict[str, Any]) -> bool:
    description = text_value(item.get("description"), "").lower()
    markers = [
        "placeholder package",
        "placeholder repository",
        "pypi name registration",
        "package scaffold",
        "lightweight package scaffold",
        "future chatarch",
        "future tooling",
    ]
    return any(marker in description for marker in markers)


def _is_python_package_like(item: dict[str, Any]) -> bool:
    category = _raw_category(item.get("category"))
    package = _mapping(item.get("package"))
    evidence = _mapping(item.get("evidence"))
    language = text_value(item.get("language"), "").lower()
    return (
        category in {"python-package", "python-package-template/early", "template/early", "python-early"}
        or bool(package.get("python_name"))
        or (language == "python" and bool(evidence.get("has_pyproject")))
    )


def _cli_surface_is_early(item: dict[str, Any]) -> bool:
    """Return True when the CLI exists but has no substantive command surface.

    ChatArch placeholder/early packages often expose only an entrypoint or global
    option flags such as `--help`/`--version`. Treat those as `Python (early)` so
    the project page does not overstate them as mature Python packages. A version
    tag alone is not a maturity signal; placeholder packages can be tagged.
    """

    cli = _mapping(item.get("cli"))
    commands = _cli_commands(item)
    if not commands:
        return False
    if commands and all(command.startswith("-") for command in commands):
        return True
    if text_value(cli.get("tree_status"), "") == "command-names-only":
        return True
    return False


def category_key(item: dict[str, Any]) -> str:
    raw = _raw_category(item.get("category"))
    mapped = CATEGORY_ALIASES.get(raw, raw)
    if _is_python_package_like(item):
        actual_business_count = _actual_business_command_count(item)
        if actual_business_count is not None and actual_business_count > 0:
            return "python-package"
        if actual_business_count == 0 and _cli_commands(item):
            return "python-early"
        if _actual_tree_status(item) == "no-entrypoint":
            return "python-early"
        if _description_is_placeholder(item):
            return "python-early"
        if raw in EARLY_PYTHON_CATEGORY_ALIASES or _cli_surface_is_early(item):
            return "python-early"
        if mapped == "python-package":
            return "python-package"
    if mapped in CATEGORY_LABELS:
        return mapped
    return "other"


def display_category(item: dict[str, Any]) -> str:
    return CATEGORY_LABELS.get(category_key(item), "其他项目")


def version_display(version: dict[str, Any] | None) -> str:
    if not isinstance(version, dict):
        return "—"
    value = text_value(version.get("value"), "")
    if not value:
        return "—"
    source = text_value(version.get("source"), "")
    return f"{value} · {source}" if source else value


def repositories(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in data.get("repositories", []) if isinstance(item, dict)]


def sorted_repos(data: dict[str, Any], sort_key: str, limit: int | None = None) -> list[dict[str, Any]]:
    repos = repositories(data)
    if sort_key == "recent":
        rows = sorted(repos, key=lambda item: text_value(item.get("pushed_at") or item.get("updated_at"), ""), reverse=True)
    elif sort_key == "triage":
        rows = [item for item in repos if int(item.get("open_prs") or 0) > 0 or int(item.get("open_issues") or 0) > 0]
        rows = sorted(
            rows,
            key=lambda item: (
                int(item.get("open_prs") or 0),
                int(item.get("open_issues") or 0),
                text_value(item.get("pushed_at") or item.get("updated_at"), ""),
            ),
            reverse=True,
        )
    elif sort_key == "category":
        order = {name: index for index, name in enumerate(CATEGORY_ORDER)}
        rows = sorted(repos, key=lambda item: (order.get(category_key(item), 999), text_value(item.get("name"), "")))
    else:
        rows = sorted(repos, key=lambda item: text_value(item.get("name"), "").lower())
    return rows[:limit] if limit else rows


def bookmark_link(item: dict[str, Any], *, url_kind: str = "repo") -> dict[str, str]:
    url = text_value(item.get("html_url"), "https://github.com/ChatArch")
    if url_kind == "docs":
        docs = item.get("docs") if isinstance(item.get("docs"), list) else []
        if docs and isinstance(docs[0], dict):
            url = text_value(docs[0].get("url"), url)
    desc_parts = [
        f"PR {int(item.get('open_prs') or 0)}",
        f"Issue {int(item.get('open_issues') or 0)}",
        f"提交 {safe_date(item.get('pushed_at') or item.get('updated_at'))}",
    ]
    version = version_display(item.get("version") if isinstance(item.get("version"), dict) else None)
    if version != "—":
        desc_parts.append(version)
    return {
        "title": text_value(item.get("name"), "unknown"),
        "url": url,
        "description": " · ".join(desc_parts),
        "icon": "si:github",
    }


def make_overview_groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    triage_count = int(counts.get("with_open_prs") or 0) + int(counts.get("with_open_issues") or 0)
    generated_at = text_value(data.get("generated_at"), "—")
    return [
        {
            "title": "概览",
            "links": [
                {"title": "可见仓库", "url": "https://github.com/ChatArch", "description": str(counts.get("visible_repos", len(repositories(data)))), "icon": "si:github"},
                {"title": "待处理 PR / Issue", "url": "https://github.com/ChatArch", "description": str(triage_count), "icon": "mdi:source-pull"},
                {"title": "刷新时间", "url": "https://github.com/ChatArch", "description": generated_at, "icon": "mdi:clock-outline"},
                {"title": "生成数据", "url": "https://github.com/ChatArch", "description": "本地生成快照 · 不含凭据", "icon": "mdi:code-json"},
            ],
        }
    ]


def make_sort_widget(data: dict[str, Any], title: str, sort_key: str) -> dict[str, Any]:
    rows = sorted_repos(data, sort_key)
    return {
        "type": "bookmarks",
        "title": title,
        "groups": [{"title": f"{title} ({len(rows)})", "links": [bookmark_link(item) for item in rows]}],
    }


def make_category_groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for category in CATEGORY_ORDER:
        rows = [item for item in sorted_repos(data, "category") if category_key(item) == category]
        if rows:
            label = CATEGORY_LABELS.get(category, category)
            groups.append({"title": f"{label} ({len(rows)})", "links": [bookmark_link(item) for item in rows]})
    remainder = [item for item in sorted_repos(data, "category") if category_key(item) not in CATEGORY_ORDER]
    if remainder:
        groups.append({"title": f"其他项目 ({len(remainder)})", "links": [bookmark_link(item) for item in remainder]})
    return groups


def make_categories_widget(data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "bookmarks", "title": "分类", "collapse-after": 12, "groups": make_category_groups(data)}


def _cli_tree_lines(item: dict[str, Any], command: str) -> list[str]:
    cli = _mapping(item.get("cli"))
    tree = _mapping(cli.get("actual_tree"))
    compact_trees = _mapping(tree.get("compact_trees"))
    compact = text_value(compact_trees.get(command), "")
    if not compact:
        entrypoints = _mapping(tree.get("entrypoints"))
        entry = _mapping(entrypoints.get(command))
        compact = text_value(entry.get("compact_tree"), "")
        if not compact:
            commands = entry.get("business_commands") if isinstance(entry.get("business_commands"), list) else tree.get("business_commands")
            placeholders = entry.get("placeholder_commands") if isinstance(entry.get("placeholder_commands"), list) else tree.get("placeholder_commands")
            nodes = [str(value).strip() for value in (commands or []) if str(value).strip() and not str(value).strip().lstrip("([{<").startswith("-")]
            nodes.extend(str(value).strip() for value in (placeholders or []) if str(value).strip() and not str(value).strip().lstrip("([{<").startswith("-"))
            compact = "\n".join([command, *(f"└── {node}" if index == len(nodes) - 1 else f"├── {node}" for index, node in enumerate(nodes))]) if nodes else command
    lines: list[str] = []
    for raw_line in compact.splitlines():
        line = raw_line.rstrip()
        token = line.split("#", 1)[0].strip().split()
        if token and token[-1].lstrip("([{<").startswith("-"):
            continue
        if line.strip():
            lines.append(line)
    return lines[:24]


def cli_cell(item: dict[str, Any]) -> str:
    commands = [command for command in _cli_commands(item) if not command.lstrip("([{<").startswith("-")]
    if not commands:
        return "—"
    chips: list[str] = []
    for command in commands[:3]:
        tree_lines = _cli_tree_lines(item, command)
        tree_html = html.escape("\n".join(tree_lines), quote=True)
        chips.append(
            '<span class="projects-cli-hover" tabindex="0">'
            f'<code>{html_text(command)}</code>'
            f'<pre class="projects-cli-tree">{tree_html}</pre>'
            '</span>'
        )
    if len(commands) > 3:
        chips.append(f'<span class="projects-cli-extra">+{len(commands) - 3}</span>')
    return " ".join(chips)


def _actual_cli_tree(item: dict[str, Any]) -> dict[str, Any]:
    return _mapping(_mapping(item.get("cli")).get("actual_tree"))


def _brief_tree_for_command(item: dict[str, Any], command: str) -> str:
    tree = _actual_cli_tree(item)
    entrypoints = _mapping(tree.get("entrypoints"))
    entry = _mapping(entrypoints.get(command))
    for source in (entry, tree):
        text = text_value(source.get("brief_tree") or source.get("tree_brief") or source.get("compact_tree"), "").strip()
        if text:
            return text
    for key in ("brief_trees", "tree_briefs", "compact_trees"):
        values = _mapping(tree.get(key))
        text = text_value(values.get(command), "").strip()
        if text:
            return text
    return ""


def _cli_brief_tree_html(item: dict[str, Any]) -> str:
    commands = [command for command in _cli_commands(item) if not command.lstrip("([{<").startswith("-")]
    blocks: list[str] = []
    for command in commands:
        tree_text = _brief_tree_for_command(item, command)
        if not tree_text:
            continue
        label = f'<div class="projects-detail-cli-tree-label"><code>{html_text(command)}</code> brief tree</div>' if len(commands) > 1 else '<div class="projects-detail-cli-tree-label">Brief tree</div>'
        blocks.append(
            '<div class="projects-detail-cli-tree-block">'
            f'{label}'
            f'<pre><code>{html.escape(tree_text, quote=True)}</code></pre>'
            '</div>'
        )
    if not blocks:
        return ""
    return f'<div class="projects-detail-cli-tree">{"".join(blocks)}</div>'


def _chatenv_meta(item: dict[str, Any]) -> dict[str, Any]:
    return _mapping(item.get("chatenv"))


def _chatenv_schemas(item: dict[str, Any]) -> list[dict[str, Any]]:
    schemas = _chatenv_meta(item).get("schemas")
    return [schema for schema in schemas if isinstance(schema, dict)] if isinstance(schemas, list) else []


def _chatenv_fields(item: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for schema in _chatenv_schemas(item):
        schema_label = text_value(schema.get("title") or schema.get("class_name"), "Env")
        class_name = text_value(schema.get("class_name"), schema_label)
        storage_dir = text_value(schema.get("storage_dir"), "")
        aliases = schema.get("aliases") if isinstance(schema.get("aliases"), list) else []
        schema_fields = schema.get("fields") if isinstance(schema.get("fields"), list) else []
        for field in schema_fields:
            if not isinstance(field, dict):
                continue
            env_key = text_value(field.get("env_key"), "")
            if not env_key:
                continue
            fields.append(
                {
                    "schema": schema_label,
                    "class_name": class_name,
                    "storage_dir": storage_dir,
                    "aliases": [str(alias) for alias in aliases],
                    "env_key": env_key,
                    "desc": text_value(field.get("desc"), "—"),
                    "sensitive": bool(field.get("sensitive")),
                    "has_default": bool(field.get("has_default")),
                }
            )
    return fields


def chatenv_cell(item: dict[str, Any]) -> str:
    fields = _chatenv_fields(item)
    if fields:
        return f'<span class="projects-env-pill">Env {len(fields)}</span>'
    meta = _chatenv_meta(item)
    if meta.get("entry_points") or _chatenv_schemas(item):
        return '<span class="projects-env-muted">Entry point</span>'
    return "—"


def _detail_metric(label: str, value: Any) -> str:
    return f'<div><span>{html_text(label)}</span><strong>{html_text(value)}</strong></div>'


def _entry_points_text(meta: dict[str, Any]) -> str:
    entry_points = meta.get("entry_points") if isinstance(meta.get("entry_points"), dict) else {}
    parts = [f"{key} -> {value}" for key, value in sorted(entry_points.items())]
    return ", ".join(parts)


def _chatenv_detail_html(item: dict[str, Any]) -> str:
    meta = _chatenv_meta(item)
    fields = _chatenv_fields(item)
    entry_points = _entry_points_text(meta)
    if fields:
        rows = []
        for field in fields:
            flags = []
            if field["sensitive"]:
                flags.append('<span class="projects-env-flag sensitive">敏感</span>')
            if field["has_default"]:
                flags.append('<span class="projects-env-flag">默认</span>')
            schema_bits = [field["schema"]]
            if field["storage_dir"]:
                schema_bits.append(field["storage_dir"])
            if field["aliases"]:
                schema_bits.append("/".join(field["aliases"]))
            rows.append(
                "<tr>"
                f'<td>{html_text(" · ".join(schema_bits))}</td>'
                f'<td><code>{html_text(field["env_key"])}</code></td>'
                f'<td>{html_text(field["desc"])}</td>'
                f'<td>{" ".join(flags) or "—"}</td>'
                "</tr>"
            )
        entry_html = f'<p class="projects-detail-note">Entry point: {html_text(entry_points)}</p>' if entry_points else ""
        return (
            '<section class="projects-detail-section">'
            '<h4>ChatEnv / ENV</h4>'
            f'{entry_html}'
            '<div class="projects-env-table-wrap"><table class="projects-env-table">'
            '<thead><tr><th>Schema</th><th>ENV</th><th>含义</th><th>标记</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody>'
            '</table></div>'
            '</section>'
        )
    if entry_points or _chatenv_schemas(item):
        reason = "已注册 chatenv.configs，但没有提取到 EnvField。" if entry_points else "发现 ChatEnv schema，但没有提取到 EnvField。"
        if entry_points:
            reason += f" Entry point: {entry_points}"
        return (
            '<section class="projects-detail-section">'
            '<h4>ChatEnv / ENV</h4>'
            f'<p class="projects-detail-empty">{html_text(reason)}</p>'
            '</section>'
        )
    return ""


def _cli_detail_html(item: dict[str, Any]) -> str:
    cli_commands = [command for command in _cli_commands(item) if not command.lstrip("([{<").startswith("-")]
    cli_html = " ".join(f'<code>{html_text(command)}</code>' for command in cli_commands) if cli_commands else "—"
    cli_tree_html = _cli_brief_tree_html(item)
    return (
        '<section class="projects-detail-section projects-detail-cli-section">'
        '<h4>CLI</h4>'
        f'<div class="projects-detail-cli">{cli_html}</div>'
        f'{cli_tree_html}'
        '</section>'
    )


def _detail_tabbed_sections(cli_html: str, chatenv_html: str, detail_id: str) -> str:
    if not chatenv_html:
        return cli_html
    group = html_text(f"{detail_id}-detail-tab")
    cli_id = html_text(f"{detail_id}-tab-cli")
    env_id = html_text(f"{detail_id}-tab-env")
    return (
        '<div class="projects-detail-tabset">'
        f'<input class="projects-detail-tab-radio projects-detail-tab-cli-radio" type="radio" id="{cli_id}" name="{group}" checked>'
        f'<input class="projects-detail-tab-radio projects-detail-tab-env-radio" type="radio" id="{env_id}" name="{group}">'
        '<div class="projects-detail-tab-nav" aria-label="详情模块切换">'
        f'<label class="projects-detail-tab-label projects-detail-tab-cli-label" for="{cli_id}">CLI</label>'
        f'<label class="projects-detail-tab-label projects-detail-tab-env-label" for="{env_id}">ENV</label>'
        '</div>'
        '<div class="projects-detail-tab-content">'
        f'<div class="projects-detail-tab-panel projects-detail-tab-cli-panel">{cli_html}</div>'
        f'<div class="projects-detail-tab-panel projects-detail-tab-env-panel">{chatenv_html}</div>'
        '</div>'
        '</div>'
    )


def _repo_detail_panel(item: dict[str, Any], detail_id: str) -> str:
    name = text_value(item.get("name"), "unknown")
    docs = item.get("docs") if isinstance(item.get("docs"), list) else []
    docs_url = docs[0].get("url") if docs and isinstance(docs[0], dict) else ""
    version = version_display(item.get("version") if isinstance(item.get("version"), dict) else None)
    metrics = "".join(
        [
            _detail_metric("PR", int(item.get("open_prs") or 0)),
            _detail_metric("Issue", int(item.get("open_issues") or 0)),
            _detail_metric("版本", version),
            _detail_metric("类型", display_category(item)),
            _detail_metric("最近提交", safe_date(item.get("pushed_at") or item.get("updated_at"))),
        ]
    )
    detail_sections = _detail_tabbed_sections(_cli_detail_html(item), _chatenv_detail_html(item), detail_id)
    links = [f'<a href="{html_text(item.get("html_url"))}" target="_blank" rel="noreferrer">GitHub</a>']
    if docs_url:
        links.append(f'<a href="{html_text(docs_url)}" target="_blank" rel="noreferrer">Docs</a>')
    description = text_value(item.get("description"), "—")
    chatenv_html = _chatenv_detail_html(item)
    return f"""
<article class="projects-detail-panel" aria-label="{html_text(name)} 详情">
  <header class="projects-detail-head">
    <div>
      <p class="projects-detail-kicker">Repository detail</p>
      <h3>{html_text(name)}</h3>
    </div>
  </header>
  <div class="projects-detail-links">{" · ".join(links)}</div>
  <p class="projects-detail-description">{html_text(description)}</p>
  <div class="projects-detail-metrics">{metrics}</div>
  {detail_sections}
</article>"""


def _repo_detail_popover_button(detail_id: str) -> str:
    return f'<button type="button" class="projects-detail-button" popovertarget="{html_text(detail_id)}">详情</button>'


def _repo_detail_popover(item: dict[str, Any], detail_id: str) -> str:
    return (
        f'<div id="{html_text(detail_id)}" class="projects-detail-popover" popover>'
        f'<button type="button" class="projects-detail-close" popovertarget="{html_text(detail_id)}" popovertargetaction="hide">关闭</button>'
        f'{_repo_detail_panel(item, detail_id)}'
        '</div>'
    )

TABLE_CATEGORY_ORDER = {
    "python-package": 0,
    "node-package": 1,
    "service/app": 2,
    "docs/site": 3,
    "other": 4,
    "python-early": 5,
}


def _sorted_repos_for_table(data: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        sorted_repos(data, "name"),
        key=lambda item: (TABLE_CATEGORY_ORDER.get(category_key(item), TABLE_CATEGORY_ORDER["other"]), text_value(item.get("name"), "").lower()),
    )


def make_table_widget(data: dict[str, Any]) -> dict[str, Any]:
    rows: list[str] = []
    popovers: list[str] = []
    for index, item in enumerate(_sorted_repos_for_table(data)):
        detail_id = f"projects-detail-{index}"
        popovers.append(_repo_detail_popover(item, detail_id))
        cli = cli_cell(item)
        docs = item.get("docs") if isinstance(item.get("docs"), list) else []
        docs_url = docs[0].get("url") if docs and isinstance(docs[0], dict) else ""
        docs_cell = f'<a href="{html_text(docs_url)}" target="_blank" rel="noreferrer">文档</a>' if docs_url else "—"
        rows.append(
            "<tr>"
            f'<td><a href="{html_text(item.get("html_url"))}" target="_blank" rel="noreferrer">{html_text(item.get("name"))}</a></td>'
            f'<td>{_repo_detail_popover_button(detail_id)}</td>'
            f'<td class="num">{int(item.get("open_prs") or 0)}</td>'
            f'<td class="num">{int(item.get("open_issues") or 0)}</td>'
            f'<td>{html_text(version_display(item.get("version") if isinstance(item.get("version"), dict) else None))}</td>'
            f'<td>{html_text(display_category(item))}</td>'
            f'<td>{chatenv_cell(item)}</td>'
            f'<td class="projects-cli-cell">{cli}</td>'
            f'<td>{docs_cell}</td>'
            f'<td>{html_text(safe_date(item.get("pushed_at") or item.get("updated_at")))}</td>'
            "</tr>"
        )
    source = """
<style>
.projects-table-wrap { overflow-x: auto; }
.projects-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
.projects-table th, .projects-table td { padding: 0.38rem 0.5rem; border-bottom: 1px solid var(--color-separator); vertical-align: top; }
.projects-table th { text-align: left; position: sticky; top: 0; background: var(--color-widget-background); z-index: 1; }
.projects-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.projects-table a { color: inherit; text-decoration: none; }
.projects-table a:hover { text-decoration: underline; }
.projects-detail-button { appearance: none; cursor: pointer; border: 1px solid var(--color-separator); border-radius: 999px; padding: 0.18rem 0.62rem; background: var(--color-background); color: var(--color-text); font: inherit; font-size: 0.82em; }
.projects-detail-button:hover { border-color: var(--color-primary); }
.projects-detail-popover { width: min(72rem, calc(100vw - 2rem)); max-height: min(82vh, 50rem); overflow: auto; margin: auto; padding: 0; border: 1px solid var(--color-separator); border-radius: 1rem; background: var(--color-widget-background); color: var(--color-text); box-shadow: 0 24px 80px rgba(0,0,0,0.45); }
.projects-detail-popover::backdrop { background: rgba(0,0,0,0.58); backdrop-filter: blur(2px); }
.projects-env-pill, .projects-env-muted, .projects-env-flag { display: inline-block; border-radius: 999px; padding: 0.08rem 0.42rem; border: 1px solid var(--color-separator); background: var(--color-background); font-size: 0.82em; white-space: nowrap; }
.projects-env-pill { color: var(--color-positive); }
.projects-env-muted { color: var(--color-text-subdued); }
.projects-env-flag { color: var(--color-text-subdued); }
.projects-env-flag.sensitive { color: var(--color-negative); }
.projects-cli-cell { min-width: 8rem; }
.projects-cli-hover { position: relative; display: inline-block; margin: 0 0.25rem 0.25rem 0; }
.projects-cli-hover code { border: 1px solid var(--color-separator); border-radius: 999px; padding: 0.08rem 0.42rem; background: var(--color-background); font-size: 0.82em; cursor: help; }
.projects-cli-tree { display: none; position: absolute; z-index: 20; left: 0; top: 1.65rem; min-width: 14rem; max-width: min(34rem, 70vw); max-height: 18rem; overflow: auto; white-space: pre; margin: 0; padding: 0.65rem 0.75rem; border: 1px solid var(--color-separator); border-radius: 0.75rem; background: var(--color-widget-background); color: var(--color-text); box-shadow: 0 18px 42px rgba(0,0,0,0.34); font-size: 0.82em; line-height: 1.45; }
.projects-cli-hover:hover .projects-cli-tree, .projects-cli-hover:focus-within .projects-cli-tree { display: block; }
.projects-cli-extra { color: var(--color-text-subdued); font-size: 0.85em; }
.projects-detail-head { display: flex; align-items: start; justify-content: space-between; gap: 1rem; margin-bottom: 0.5rem; }
.projects-detail-head h3 { margin: 0; font-size: 1.35rem; }
.projects-detail-kicker, .projects-detail-note, .projects-detail-empty { margin: 0; color: var(--color-text-subdued); font-size: 0.86em; }
.projects-detail-close { position: sticky; top: 0.7rem; float: right; z-index: 2; margin: 0.7rem 0.7rem 0 0; border: 1px solid var(--color-separator); border-radius: 999px; padding: 0.22rem 0.65rem; background: var(--color-background); color: inherit; font: inherit; cursor: pointer; }
.projects-detail-panel { padding: 1rem; }
.projects-detail-links, .projects-detail-description { margin: 0.45rem 0; }
.projects-detail-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(7rem, 1fr)); gap: 0.5rem; margin: 0.8rem 0; }
.projects-detail-metrics div { border: 1px solid var(--color-separator); border-radius: 0.75rem; padding: 0.5rem; background: var(--color-background); }
.projects-detail-metrics span { display: block; color: var(--color-text-subdued); font-size: 0.78em; }
.projects-detail-metrics strong { display: block; margin-top: 0.15rem; }
.projects-detail-section { margin-top: 1rem; }
.projects-detail-section h4 { margin: 0 0 0.45rem 0; }
.projects-detail-tabset { display: grid; grid-template-columns: minmax(8rem, 11rem) minmax(0, 1fr); gap: 0.8rem; align-items: start; margin-top: 1rem; }
.projects-detail-tab-radio { position: absolute; opacity: 0; pointer-events: none; }
.projects-detail-tab-nav { display: flex; flex-direction: column; gap: 0.45rem; position: sticky; top: 3rem; }
.projects-detail-tab-label { display: flex; align-items: center; justify-content: space-between; cursor: pointer; border: 1px solid var(--color-separator); border-radius: 0.8rem; padding: 0.55rem 0.7rem; background: var(--color-background); color: var(--color-text-subdued); font-weight: 600; }
.projects-detail-tab-label:hover { border-color: var(--color-primary); color: var(--color-text); }
.projects-detail-tab-panel { display: none; }
.projects-detail-tab-cli-radio:checked ~ .projects-detail-tab-nav .projects-detail-tab-cli-label, .projects-detail-tab-env-radio:checked ~ .projects-detail-tab-nav .projects-detail-tab-env-label { border-color: var(--color-primary); color: var(--color-text); box-shadow: inset 3px 0 0 var(--color-primary); }
.projects-detail-tab-cli-radio:checked ~ .projects-detail-tab-content .projects-detail-tab-cli-panel, .projects-detail-tab-env-radio:checked ~ .projects-detail-tab-content .projects-detail-tab-env-panel { display: block; }
.projects-detail-tab-content .projects-detail-section { margin-top: 0; }
.projects-detail-cli code { display: inline-block; margin: 0 0.25rem 0.25rem 0; border: 1px solid var(--color-separator); border-radius: 999px; padding: 0.08rem 0.42rem; background: var(--color-background); }
.projects-detail-cli-tree { margin-top: 0.65rem; }
.projects-detail-cli-tree-block { margin-top: 0.55rem; }
.projects-detail-cli-tree-label { margin: 0 0 0.25rem 0; color: var(--color-text-subdued); font-size: 0.82em; }
.projects-detail-cli-tree-label code { border: 1px solid var(--color-separator); border-radius: 999px; padding: 0.04rem 0.34rem; background: var(--color-background); color: var(--color-text); }
.projects-detail-cli-tree pre { margin: 0; max-height: 32rem; overflow: auto; white-space: pre; border: 1px solid var(--color-separator); border-radius: 0.8rem; padding: 0.75rem 0.85rem; background: var(--color-background); color: var(--color-text); font-size: 0.84em; line-height: 1.45; }
.projects-env-table-wrap { overflow-x: auto; }
.projects-env-table { width: 100%; border-collapse: collapse; font-size: 0.88em; }
.projects-env-table th, .projects-env-table td { padding: 0.34rem 0.45rem; border-bottom: 1px solid var(--color-separator); text-align: left; vertical-align: top; }
.projects-env-table code { white-space: nowrap; }
@media (max-width: 720px) { .projects-detail-popover { width: calc(100vw - 1rem); max-height: 92vh; } .projects-detail-tabset { grid-template-columns: 1fr; } .projects-detail-tab-nav { position: static; flex-direction: row; } .projects-detail-tab-label { flex: 1; justify-content: center; } }
</style>
<div id="projects-table-root" class="projects-table-wrap">
<table class="projects-table">
<thead><tr><th>仓库</th><th>详情</th><th>PR</th><th>Issue</th><th>版本</th><th>类型</th><th>Env</th><th>CLI</th><th>文档</th><th>最近提交</th></tr></thead>
<tbody>
""" + "\n".join(rows) + """
</tbody>
</table>
</div>
""" + "\n".join(popovers)
    return {"type": "html", "title": "一览表", "source": source}


def build_projects_page(data: dict[str, Any], *, page_name: str = PAGE_NAME) -> dict[str, Any]:
    """Build the Glance page object for the ChatArch projects dashboard."""

    page = {
        "name": page_name,
        "columns": [
            {"size": "small", "widgets": [{"type": "bookmarks", "title": "概览", "groups": make_overview_groups(data)}]},
            {
                "size": "full",
                "widgets": [
                    {
                        "type": "group",
                        "widgets": [
                            make_sort_widget(data, "最近提交", "recent"),
                            make_sort_widget(data, "待处理 PR / Issue", "triage"),
                            make_categories_widget(data),
                            make_table_widget(data),
                        ],
                    }
                ],
            },
        ],
    }
    return page


def dump_yaml(value: Any) -> str:
    import yaml

    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=120)
