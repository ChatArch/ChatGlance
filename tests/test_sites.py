from __future__ import annotations

import sqlite3

import yaml

from chatglance.sites import (
    SITES_PAGE_NAME,
    apply_gatus_status,
    build_sites_page,
    export_site_covers,
    load_sites_inventory,
    render_sites_html,
    replace_sites_page,
)


def sample_sites_data() -> dict:
    return {
        "generated_at": "2026-08-12T03:50:00+08:00",
        "counts": {"sites": 2, "healthy": 1, "monitored": 2},
        "sites": [
            {
                "name": "glance",
                "title": "Glance",
                "description": "ChatArch dashboard.",
                "public_url": "https://glance.public.wzhecnu.cn/",
                "local_host": "glance.local.wzhecnu.cn",
                "status": "healthy",
                "status_code": 200,
                "uptime_url": "https://uptime.public.wzhecnu.cn/endpoints/chatarch-services_glance",
            },
            {
                "name": "zulip",
                "title": "Zulip",
                "description": "Structured realtime chat workspace.",
                "public_url": "https://zulip.public.wzhecnu.cn/",
                "local_host": "zulip.local.wzhecnu.cn",
                "status": "unknown",
                "uptime_url": "https://uptime.public.wzhecnu.cn/endpoints/chatarch-services_zulip",
            },
        ],
    }


def test_render_sites_html_uses_cards_covers_public_buttons_and_hides_local_hosts() -> None:
    html = render_sites_html(sample_sites_data())

    assert "网站服务 2 个" in html
    assert "健康 1 个" in html
    assert "data:image/svg+xml;base64," in html
    assert "ChatArch dashboard." in html
    assert "https://glance.public.wzhecnu.cn/" in html
    assert "打开" in html
    assert "↗" in html
    assert "Uptime" in html
    assert "https://uptime.public.wzhecnu.cn/endpoints/chatarch-services_glance" in html
    assert "glance.local.wzhecnu.cn" not in html
    assert "zulip.local.wzhecnu.cn" not in html


def test_render_sites_html_prefers_external_cover_url_when_present() -> None:
    data = sample_sites_data()
    data["sites"][0]["cover_url"] = "https://share.public.wzhecnu.cn/covers/glance.svg"

    html = render_sites_html(data)

    assert "https://share.public.wzhecnu.cn/covers/glance.svg" in html
    first_card = html.split("</article>", 1)[0]
    assert "data:image/svg+xml;base64," not in first_card


def test_build_sites_page_creates_wide_html_page() -> None:
    page = build_sites_page(sample_sites_data())

    assert page["name"] == SITES_PAGE_NAME
    assert page["slug"] == "sites"
    assert page["width"] == "wide"
    assert page["columns"][0]["widgets"][0]["type"] == "html"
    assert page["columns"][0]["widgets"][0]["title"] == "网站服务"


def test_replace_sites_page_appends_after_server_page_and_removes_old_slug() -> None:
    config = {
        "pages": [
            {"name": "ChatArch"},
            {"name": "项目"},
            {"name": "网站服务", "slug": "sites", "old": True},
            {"name": "服务器", "slug": "servers"},
        ]
    }

    updated = replace_sites_page(config, sample_sites_data())

    assert [page["name"] for page in updated["pages"]] == ["ChatArch", "项目", "服务器", "网站服务"]
    assert updated["pages"][-1]["slug"] == "sites"
    assert config["pages"][2]["old"] is True


def test_load_sites_inventory_builds_public_urls_and_uptime_urls(tmp_path) -> None:
    inventory = tmp_path / "sites.yml"
    inventory.write_text(
        """
page:
  name: 网站服务
  slug: sites
  widget_title: 网站服务
  uptime_base_url: https://uptime.public.wzhecnu.cn/
sites:
  - name: glance
    title: Glance
    description: ChatArch dashboard.
  - name: gitea
    title: Gitea
    description: Self-hosted Git service.
""".strip(),
        encoding="utf-8",
    )

    data = load_sites_inventory(inventory, generated_at="2026-08-12T03:55:00+08:00")

    assert data["counts"]["sites"] == 2
    assert data["sites"][0]["public_url"] == "https://glance.public.wzhecnu.cn/"
    assert data["sites"][0]["uptime_url"] == "https://uptime.public.wzhecnu.cn/endpoints/chatarch-services_glance"
    assert data["sites"][0]["local_host"] == "glance.local.wzhecnu.cn"


def test_apply_gatus_status_reads_latest_endpoint_results(tmp_path) -> None:
    db_path = tmp_path / "gatus.db"
    con = sqlite3.connect(db_path)
    con.execute("create table endpoints(endpoint_id integer primary key, endpoint_key text, endpoint_name text, endpoint_group text)")
    con.execute("create table endpoint_results(endpoint_result_id integer primary key, endpoint_id integer, success integer, errors text, connected integer, status integer, timestamp text)")
    con.execute("insert into endpoints values(1, 'chatarch-services_glance', 'glance', 'ChatArch Services')")
    con.execute("insert into endpoint_results values(1, 1, 0, 'bad', 1, 503, 'old')")
    con.execute("insert into endpoint_results values(2, 1, 1, '', 1, 200, 'new')")
    con.commit()
    con.close()
    data = sample_sites_data()
    data["sites"][0]["status"] = "unknown"

    updated = apply_gatus_status(data, db_path)

    glance = updated["sites"][0]
    assert glance["status"] == "healthy"
    assert glance["status_code"] == 200
    assert glance["checked_at"] == "new"
    assert updated["counts"]["healthy"] == 1


def test_export_site_covers_writes_svg_files_and_attaches_public_urls(tmp_path) -> None:
    data = sample_sites_data()

    updated = export_site_covers(data, tmp_path, public_base_url="https://share.public.wzhecnu.cn/covers/")

    glance_cover = tmp_path / "glance.svg"
    zulip_cover = tmp_path / "zulip.svg"
    assert glance_cover.exists()
    assert zulip_cover.exists()
    assert "<svg" in glance_cover.read_text(encoding="utf-8")
    assert updated["sites"][0]["cover_url"] == "https://share.public.wzhecnu.cn/covers/glance.svg"
    assert updated["sites"][1]["cover_url"] == "https://share.public.wzhecnu.cn/covers/zulip.svg"
    assert "cover_url" not in data["sites"][0]
