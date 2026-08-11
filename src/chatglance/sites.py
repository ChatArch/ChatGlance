"""Build reviewed website-service cards for the ChatArch Glance dashboard."""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import html
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, cast

import yaml

SITES_PAGE_NAME = "网站服务"
LEGACY_SITES_PAGE_NAMES = {"Sites", "Website Services", "站点", "网站"}
DEFAULT_PAGE_SLUG = "sites"
DEFAULT_WIDGET_TITLE = "网站服务"
DEFAULT_UPTIME_BASE_URL = "https://uptime.public.wzhecnu.cn/"
DEFAULT_GATUS_GROUP = "ChatArch Services"
BEIJING_TZ = timezone(timedelta(hours=8))

PALETTE = [
    ("#5B8CFF", "#7C3AED"),
    ("#14B8A6", "#2563EB"),
    ("#F97316", "#DB2777"),
    ("#22C55E", "#0EA5E9"),
    ("#A855F7", "#EC4899"),
    ("#F59E0B", "#10B981"),
]


def beijing_now() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def text_value(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def html_text(value: Any, fallback: str = "—") -> str:
    return html.escape(text_value(value, fallback), quote=True)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "site"


def gatus_endpoint_key(name: str, *, group: str = DEFAULT_GATUS_GROUP) -> str:
    return f"{slugify(group)}_{slugify(name)}"


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def _public_url(name: str) -> str:
    return f"https://{name}.public.wzhecnu.cn/"


def _local_host(name: str) -> str:
    return f"{name}.local.wzhecnu.cn"


def _uptime_url(name: str, base_url: str = DEFAULT_UPTIME_BASE_URL) -> str:
    return _ensure_trailing_slash(base_url) + "endpoints/" + gatus_endpoint_key(name)


def _cover_svg(site: dict[str, Any]) -> str:
    name = text_value(site.get("name"), "site")
    title = text_value(site.get("title"), name)
    label = (text_value(site.get("cover_label")) or title[:2]).upper()
    palette = PALETTE[sum(ord(ch) for ch in name) % len(PALETTE)]
    safe_title = html.escape(title)
    safe_name = html.escape(name)
    safe_label = html.escape(label[:4])
    return f"""<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"640\" height=\"280\" viewBox=\"0 0 640 280\" role=\"img\" aria-label=\"{safe_title} cover\">
  <defs>
    <linearGradient id=\"g\" x1=\"0\" x2=\"1\" y1=\"0\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"{palette[0]}\"/>
      <stop offset=\"100%\" stop-color=\"{palette[1]}\"/>
    </linearGradient>
    <filter id=\"shadow\" x=\"-20%\" y=\"-20%\" width=\"140%\" height=\"140%\">
      <feDropShadow dx=\"0\" dy=\"18\" stdDeviation=\"18\" flood-color=\"#020617\" flood-opacity=\"0.25\"/>
    </filter>
  </defs>
  <rect width=\"640\" height=\"280\" rx=\"28\" fill=\"url(#g)\"/>
  <circle cx=\"532\" cy=\"52\" r=\"110\" fill=\"#fff\" opacity=\"0.14\"/>
  <circle cx=\"90\" cy=\"246\" r=\"150\" fill=\"#020617\" opacity=\"0.15\"/>
  <g filter=\"url(#shadow)\">
    <rect x=\"48\" y=\"54\" width=\"150\" height=\"150\" rx=\"34\" fill=\"#ffffff\" opacity=\"0.92\"/>
    <text x=\"123\" y=\"146\" text-anchor=\"middle\" font-family=\"Inter, ui-sans-serif, system-ui, sans-serif\" font-size=\"48\" font-weight=\"800\" fill=\"{palette[1]}\">{safe_label}</text>
  </g>
  <text x=\"230\" y=\"112\" font-family=\"Inter, ui-sans-serif, system-ui, sans-serif\" font-size=\"42\" font-weight=\"800\" fill=\"#ffffff\">{safe_title}</text>
  <text x=\"232\" y=\"160\" font-family=\"Inter, ui-sans-serif, system-ui, sans-serif\" font-size=\"22\" font-weight=\"600\" fill=\"#ffffff\" opacity=\"0.82\">{safe_name}.public.wzhecnu.cn</text>
  <path d=\"M232 194 H500\" stroke=\"#fff\" stroke-width=\"3\" stroke-linecap=\"round\" opacity=\"0.38\"/>
  <text x=\"232\" y=\"230\" font-family=\"Inter, ui-sans-serif, system-ui, sans-serif\" font-size=\"18\" fill=\"#ffffff\" opacity=\"0.78\">ChatArch Service Entry</text>
</svg>"""


def cover_data_uri(site: dict[str, Any]) -> str:
    raw = _cover_svg(site).encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")


def _status_label(status: str) -> str:
    return {"healthy": "健康", "unhealthy": "异常", "unknown": "未知"}.get(status or "unknown", status or "未知")


def _site_card(site: dict[str, Any]) -> str:
    status = text_value(site.get("status"), "unknown")
    public_url = text_value(site.get("public_url"))
    uptime_url = text_value(site.get("uptime_url"))
    status_code = site.get("status_code")
    status_piece = f"HTTP {html_text(status_code)}" if status_code not in (None, "") else "Uptime"
    uptime_button = (
        f'<a class="site-btn secondary" href="{html_text(uptime_url)}" target="_blank" rel="noreferrer">Uptime</a>'
        if uptime_url
        else ""
    )
    return f"""
<article class="site-card status-{html_text(status, 'unknown')}">
  <div class="site-cover-wrap"><img class="site-cover" src="{html_text(site.get('cover_url') or cover_data_uri(site))}" alt="{html_text(site.get('title') or site.get('name'))} cover" loading="lazy"></div>
  <div class="site-card-body">
    <div class="site-card-head">
      <div>
        <h3>{html_text(site.get('title') or site.get('name'))}</h3>
        <p class="site-kind">{html_text(site.get('kind'), 'ChatArch service')}</p>
      </div>
      <span class="site-pill">{html_text(_status_label(status))}</span>
    </div>
    <p class="site-description">{html_text(site.get('description'), '—')}</p>
    <div class="site-meta"><span>{html_text(status_piece)}</span><span>更新 {html_text(site.get('checked_at') or site.get('generated_at'), '—')}</span></div>
    <div class="site-actions">
      <a class="site-btn primary" href="{html_text(public_url)}" target="_blank" rel="noreferrer">打开 <span aria-hidden="true">↗</span></a>
      {uptime_button}
    </div>
  </div>
</article>"""


def render_sites_html(data: dict[str, Any]) -> str:
    sites = [item for item in data.get("sites", []) if isinstance(item, dict)]
    counts = cast(dict[str, Any], data.get("counts")) if isinstance(data.get("counts"), dict) else {}
    generated_at = html_text(data.get("generated_at"))
    healthy = int(counts.get("healthy") or sum(1 for item in sites if item.get("status") == "healthy"))
    monitored = int(counts.get("monitored") or sum(1 for item in sites if item.get("uptime_url")))
    cards = "\n".join(_site_card(item) for item in sites)
    return f"""
<style>
.site-summary {{ margin-bottom: 0.8rem; color: var(--color-text-subdue); }}
.site-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 0.9rem; }}
.site-card {{ border: 1px solid var(--color-separator); border-radius: 18px; overflow: hidden; background: var(--color-widget-background); box-shadow: 0 8px 28px rgba(15,23,42,0.08); }}
.site-cover-wrap {{ aspect-ratio: 16 / 7; overflow: hidden; background: rgba(148,163,184,0.12); }}
.site-cover {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
.site-card-body {{ padding: 0.82rem; }}
.site-card-head {{ display: flex; justify-content: space-between; gap: 0.6rem; align-items: flex-start; }}
.site-card h3 {{ margin: 0; font-size: 1.05rem; }}
.site-kind {{ margin: 0.15rem 0 0; font-size: 0.78rem; color: var(--color-text-subdue); }}
.site-pill {{ border: 1px solid var(--color-separator); border-radius: 999px; padding: 0.12rem 0.5rem; font-size: 0.76rem; white-space: nowrap; }}
.status-healthy .site-pill {{ color: var(--color-positive); }}
.status-unhealthy .site-pill {{ color: var(--color-negative); }}
.site-description {{ min-height: 2.7em; margin: 0.65rem 0; color: var(--color-text); line-height: 1.45; }}
.site-meta {{ display: flex; flex-wrap: wrap; gap: 0.45rem; color: var(--color-text-subdue); font-size: 0.76rem; margin-bottom: 0.75rem; }}
.site-actions {{ display: flex; flex-wrap: wrap; gap: 0.5rem; }}
.site-btn {{ display: inline-flex; align-items: center; gap: 0.28rem; border: 1px solid var(--color-separator); border-radius: 999px; padding: 0.32rem 0.68rem; font-size: 0.82rem; text-decoration: none; }}
.site-btn.primary {{ background: var(--color-primary); color: var(--color-widget-background); border-color: var(--color-primary); }}
.site-btn.secondary {{ color: var(--color-text); }}
</style>
<div class="site-summary">最新整理：{generated_at} · 网站服务 {len(sites)} 个 · 健康 {healthy} 个 · Uptime 监控 {monitored} 个</div>
<div class="site-grid">
{cards or '<p>暂无网站服务数据。</p>'}
</div>
"""


def _recount(data: dict[str, Any]) -> dict[str, Any]:
    sites = [item for item in data.get("sites", []) if isinstance(item, dict)]
    counts = {
        "sites": len(sites),
        "healthy": sum(1 for item in sites if item.get("status") == "healthy"),
        "unhealthy": sum(1 for item in sites if item.get("status") == "unhealthy"),
        "monitored": sum(1 for item in sites if item.get("uptime_url")),
    }
    data["counts"] = counts
    return data


def load_sites_inventory(path: str | Path, *, generated_at: str | None = None) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("site inventory config must be a YAML object")
    page = raw.get("page") if isinstance(raw.get("page"), dict) else {}
    uptime_base_url = text_value(cast(dict[str, Any], page).get("uptime_base_url"), DEFAULT_UPTIME_BASE_URL)
    entries = raw.get("sites") or []
    if not isinstance(entries, list):
        raise ValueError("sites must be a list")
    sites: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("site entries must be mappings")
        name = text_value(entry.get("name"))
        if not name:
            raise ValueError("site entry requires name")
        site = dict(entry)
        site.setdefault("title", name)
        site.setdefault("kind", "ChatArch service")
        site["public_url"] = text_value(site.get("public_url"), _public_url(name))
        site["local_host"] = text_value(site.get("local_host"), _local_host(name))
        site["uptime_url"] = text_value(site.get("uptime_url"), _uptime_url(name, uptime_base_url))
        site.setdefault("status", "unknown")
        sites.append(site)
    return _recount({"generated_at": generated_at or beijing_now(), "sites": sites})


def load_sites_data(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("site-services JSON must be an object")
    if not isinstance(data.get("sites"), list):
        raise ValueError("site-services JSON must contain a sites list")
    return data


def dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def apply_gatus_status(data: dict[str, Any], db_path: str | Path, *, group: str = DEFAULT_GATUS_GROUP) -> dict[str, Any]:
    updated = deepcopy(data)
    db = Path(db_path)
    if not db.exists():
        return _recount(updated)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """
            select e.endpoint_key, e.endpoint_name, r.success, r.errors, r.status, r.timestamp
            from endpoint_results r
            join endpoints e using(endpoint_id)
            where e.endpoint_group = ?
              and r.endpoint_result_id in (
                select max(r2.endpoint_result_id)
                from endpoint_results r2 join endpoints e2 using(endpoint_id)
                where e2.endpoint_group = ?
                group by e2.endpoint_key
              )
            """,
            (group, group),
        ).fetchall()
    finally:
        con.close()
    by_key = {str(row[0]): row for row in rows}
    by_name = {str(row[1]): row for row in rows}
    for site in updated.get("sites", []):
        if not isinstance(site, dict):
            continue
        name = text_value(site.get("name"))
        row = by_key.get(gatus_endpoint_key(name, group=group)) or by_name.get(name)
        if not row:
            continue
        success = bool(row[2])
        site["status"] = "healthy" if success else "unhealthy"
        site["status_code"] = row[4]
        site["checked_at"] = row[5]
        if row[3]:
            site["status_error"] = row[3]
    return _recount(updated)


def export_site_covers(data: dict[str, Any], output_dir: str | Path, *, public_base_url: str | None = None) -> dict[str, Any]:
    """Write generated SVG cover images and optionally attach public cover URLs."""

    updated = deepcopy(data)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    base_url = _ensure_trailing_slash(public_base_url) if public_base_url else None
    for site in updated.get("sites", []):
        if not isinstance(site, dict):
            continue
        name = text_value(site.get("name"))
        if not name:
            continue
        filename = f"{slugify(name)}.svg"
        (directory / filename).write_text(_cover_svg(site), encoding="utf-8")
        if base_url:
            site["cover_url"] = base_url + filename
    return updated


def build_sites_page(
    data: dict[str, Any],
    *,
    page_name: str = SITES_PAGE_NAME,
    page_slug: str = DEFAULT_PAGE_SLUG,
    widget_title: str = DEFAULT_WIDGET_TITLE,
) -> dict[str, Any]:
    return {
        "name": page_name,
        "slug": page_slug,
        "width": "wide",
        "columns": [
            {
                "size": "full",
                "widgets": [
                    {
                        "type": "html",
                        "title": widget_title,
                        "source": render_sites_html(data),
                    }
                ],
            }
        ],
    }


def replace_sites_page(
    config: dict[str, Any],
    data: dict[str, Any],
    *,
    page_name: str = SITES_PAGE_NAME,
    page_slug: str = DEFAULT_PAGE_SLUG,
    widget_title: str = DEFAULT_WIDGET_TITLE,
) -> dict[str, Any]:
    updated = deepcopy(config)
    pages = updated.setdefault("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Glance config `pages` must be a list")
    legacy_names = set(LEGACY_SITES_PAGE_NAMES) | {page_name}
    pages[:] = [page for page in pages if not (isinstance(page, dict) and (page.get("name") in legacy_names or page.get("slug") == page_slug))]
    new_page = build_sites_page(data, page_name=page_name, page_slug=page_slug, widget_title=widget_title)
    insert_after = None
    for index, page in enumerate(pages):
        if isinstance(page, dict) and (page.get("slug") == "servers" or page.get("name") == "服务器"):
            insert_after = index
    if insert_after is None:
        for index, page in enumerate(pages):
            if isinstance(page, dict) and page.get("name") == "项目":
                insert_after = index
    if insert_after is None:
        for index, page in enumerate(pages):
            if isinstance(page, dict) and page.get("name") == "ChatArch":
                insert_after = index
    if insert_after is None:
        pages.append(new_page)
    else:
        pages.insert(insert_after + 1, new_page)
    return updated
