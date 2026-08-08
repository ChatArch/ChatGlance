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
    "node-package": "Node / npm 包",
    "service/app": "服务 / 应用",
    "docs/site": "文档 / 站点",
    "template/early": "模板 / 早期包",
    "other": "其他项目",
}
CATEGORY_ORDER = ["python-package", "node-package", "service/app", "docs/site", "template/early", "other"]


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
        rows = sorted(repos, key=lambda item: (order.get(text_value(item.get("category"), "other"), 999), text_value(item.get("name"), "")))
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
    return [
        {
            "title": "概览",
            "links": [
                {"title": "可见仓库", "url": "https://github.com/ChatArch", "description": str(counts.get("visible_repos", len(repositories(data)))), "icon": "si:github"},
                {"title": "待处理 PR / Issue", "url": "https://github.com/ChatArch", "description": str(triage_count), "icon": "mdi:source-pull"},
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
        rows = [item for item in sorted_repos(data, "category") if text_value(item.get("category"), "other") == category]
        if rows:
            groups.append({"title": CATEGORY_LABELS.get(category, category), "links": [bookmark_link(item) for item in rows]})
    remainder = [item for item in sorted_repos(data, "category") if text_value(item.get("category"), "other") not in CATEGORY_ORDER]
    if remainder:
        groups.append({"title": "其他项目", "links": [bookmark_link(item) for item in remainder]})
    return groups


def make_categories_widget(data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "bookmarks", "title": "分类", "collapse-after": 12, "groups": make_category_groups(data)}


def make_table_widget(data: dict[str, Any]) -> dict[str, Any]:
    rows: list[str] = []
    for item in sorted_repos(data, "name"):
        commands = ((item.get("cli") or {}).get("commands") if isinstance(item.get("cli"), dict) else []) or []
        cli = ", ".join(str(command) for command in commands[:3])
        if len(commands) > 3:
            cli += f" +{len(commands) - 3}"
        docs = item.get("docs") if isinstance(item.get("docs"), list) else []
        docs_url = docs[0].get("url") if docs and isinstance(docs[0], dict) else ""
        docs_cell = f'<a href="{html_text(docs_url)}" target="_blank" rel="noreferrer">文档</a>' if docs_url else "—"
        rows.append(
            "<tr>"
            f'<td><a href="{html_text(item.get("html_url"))}" target="_blank" rel="noreferrer">{html_text(item.get("name"))}</a></td>'
            f'<td class="num">{int(item.get("open_prs") or 0)}</td>'
            f'<td class="num">{int(item.get("open_issues") or 0)}</td>'
            f'<td>{html_text(version_display(item.get("version") if isinstance(item.get("version"), dict) else None))}</td>'
            f'<td>{html_text(CATEGORY_LABELS.get(text_value(item.get("category"), "other"), text_value(item.get("category"), "other")))}</td>'
            f'<td>{html_text(cli)}</td>'
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
</style>
<div class="projects-table-wrap">
<table class="projects-table">
<thead><tr><th>仓库</th><th>PR</th><th>Issue</th><th>版本</th><th>类型</th><th>CLI</th><th>文档</th><th>最近提交</th></tr></thead>
<tbody>
""" + "\n".join(rows) + """
</tbody>
</table>
</div>
"""
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
