import yaml

from chatglance.glance_config import patch_server_stats_root_only, replace_projects_page
from chatglance.projects import build_projects_page


def sample_inventory():
    return {
        "counts": {"visible_repos": 3, "with_open_prs": 1, "with_open_issues": 1},
        "repositories": [
            {
                "name": "alpha",
                "html_url": "https://github.com/ChatArch/alpha",
                "open_prs": 0,
                "open_issues": 0,
                "pushed_at": "2026-08-01T00:00:00Z",
                "category": "python-package",
                "version": {"value": "0.1.0", "source": "pyproject.toml"},
                "cli": {"commands": ["alpha"]},
                "docs": [{"url": "https://example.invalid/alpha"}],
            },
            {
                "name": "beta",
                "html_url": "https://github.com/ChatArch/beta",
                "open_prs": 1,
                "open_issues": 0,
                "pushed_at": "2026-08-03T00:00:00Z",
                "category": "service/app",
                "version": {},
                "cli": {"commands": []},
                "docs": [],
            },
            {
                "name": "gamma",
                "html_url": "https://github.com/ChatArch/gamma",
                "open_prs": 0,
                "open_issues": 2,
                "pushed_at": "2026-08-02T00:00:00Z",
                "category": "docs/site",
                "version": {},
                "cli": {"commands": []},
                "docs": [],
            },
        ],
    }


def group_tab_titles(page):
    full_col = page["columns"][1]
    group = full_col["widgets"][0]
    return [widget["title"] for widget in group["widgets"]]


def test_build_projects_page_has_only_current_tabs():
    page = build_projects_page(sample_inventory())

    assert group_tab_titles(page) == ["最近提交", "待处理 PR / Issue", "分类", "一览表"]
    rendered = yaml.safe_dump(page, allow_unicode=True, sort_keys=False)
    assert "按名称" not in rendered
    assert "命令与文档" not in rendered


def test_triage_tab_filters_zero_zero_repositories():
    page = build_projects_page(sample_inventory())
    triage_widget = page["columns"][1]["widgets"][0]["widgets"][1]
    links = triage_widget["groups"][0]["links"]

    assert [link["title"] for link in links] == ["beta", "gamma"]


def test_replace_projects_page_removes_legacy_generated_pages():
    config = {"pages": [{"name": "ChatArch"}, {"name": "ChatArch Projects"}, {"name": "项目"}]}
    updated = replace_projects_page(config, sample_inventory())

    assert [page["name"] for page in updated["pages"]] == ["ChatArch", "项目"]


def test_patch_server_stats_root_only_hides_default_mountpoints():
    config = {
        "pages": [
            {
                "name": "ChatArch",
                "columns": [
                    {
                        "size": "small",
                        "widgets": [
                            {
                                "type": "server-stats",
                                "servers": [{"type": "local", "name": "rexpc"}],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    updated = patch_server_stats_root_only(config)
    widget = updated["pages"][0]["columns"][0]["widgets"][0]
    server = widget["servers"][0]

    assert widget["hide-mountpoints-by-default"] is True
    assert server["hide-mountpoints-by-default"] is True
    assert server["hide-swap"] is True
    assert server["mountpoints"] == {"/": {"name": "根分区"}}
