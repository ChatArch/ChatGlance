import yaml

from chatglance.glance_config import patch_server_stats_root_only, replace_projects_page
from chatglance.projects import build_projects_page, category_key, display_category


def sample_inventory():
    return {
        "generated_at": "2026-08-11T17:30:00+08:00",
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
                "cli": {
                    "commands": ["alpha"],
                    "actual_tree": {
                        "status": "ok",
                        "business_commands": ["projects", "collect", "render-page"],
                        "business_command_count": 3,
                        "global_options": ["--help", "--version", "--tree"],
                        "entrypoints": {
                            "alpha": {
                                "status": "ok",
                                "business_commands": ["projects", "collect", "render-page"],
                                "business_command_count": 3,
                                "global_options": ["--help", "--version", "--tree"],
                            }
                        },
                    },
                },
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
            {
                "name": "ChatFlow",
                "html_url": "https://github.com/ChatArch/ChatFlow",
                "open_prs": 0,
                "open_issues": 0,
                "pushed_at": "2026-06-27T00:00:00Z",
                "category": "python-package",
                "language": "Python",
                "package": {"python_name": "ChatFlow"},
                "version": {"value": None, "source": None},
                "cli": {"commands": ["chatflow"], "tree_status": "command-names-only"},
                "evidence": {"has_pyproject": True},
                "docs": [],
            },
            {
                "name": "delta-template",
                "html_url": "https://github.com/ChatArch/delta-template",
                "open_prs": 0,
                "open_issues": 0,
                "pushed_at": "2026-08-04T00:00:00Z",
                "category": "python-package-template/early",
                "version": {},
                "cli": {"commands": ["--help", "--version"]},
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


def test_project_category_display_normalizes_early_python_packages():
    data = sample_inventory()
    repos = {item["name"]: item for item in data["repositories"]}

    assert category_key(repos["ChatFlow"]) == "python-early"
    assert display_category(repos["ChatFlow"]) == "Python (early)"
    assert category_key(repos["delta-template"]) == "python-early"
    assert display_category(repos["delta-template"]) == "Python (early)"

    page = build_projects_page(data)
    rendered = yaml.safe_dump(page, allow_unicode=True, sort_keys=False)
    assert "Python (early)" in rendered
    assert "python-package-template/early" not in rendered
    assert "模板 / 早期包" not in rendered


def test_project_category_keeps_reviewed_early_category_even_with_cli_entry():
    chatcrs = {
        "name": "ChatCRS",
        "html_url": "https://github.com/ChatArch/ChatCRS",
        "category": "python-package-template/early",
        "language": "Python",
        "package": {"python_name": "ChatCRS"},
        "version": {"value": "0.2.5", "source": "pypi"},
        "cli": {"commands": ["chatcrs"], "tree_status": "entrypoint-only"},
        "evidence": {"has_pyproject": True},
    }

    assert category_key(chatcrs) == "python-early"
    assert display_category(chatcrs) == "Python (early)"


def test_project_category_treats_reviewed_early_python_cli_as_early():
    for name, command, version in [("ChatSMTP", "chatsmtp", "0.1.0"), ("ChatSync", "chatsync", "0.0.2")]:
        item = {
            "name": name,
            "html_url": f"https://github.com/ChatArch/{name}",
            "category": "python-package-template/early",
            "language": "Python",
            "package": {"python_name": name},
            "version": {"value": version, "source": "pypi"},
            "cli": {"commands": [command], "tree_status": "entrypoint-only"},
            "evidence": {"has_pyproject": True},
        }

        assert category_key(item) == "python-early"
        assert display_category(item) == "Python (early)"


def test_project_category_treats_no_entrypoint_python_repo_as_early() -> None:
    item = {
        "name": "ChatStyle",
        "category": "python-package",
        "language": "Python",
        "package": {"python_name": "ChatStyle"},
        "cli": {
            "commands": [],
            "actual_tree": {
                "status": "no-entrypoint",
                "business_commands": [],
                "business_command_count": 0,
            },
        },
        "evidence": {"has_pyproject": True},
    }

    assert category_key(item) == "python-early"
    assert display_category(item) == "Python (early)"


def test_project_overview_shows_inventory_refresh_time():
    page = build_projects_page(sample_inventory())
    rendered = yaml.safe_dump(page, allow_unicode=True, sort_keys=False)

    assert "刷新时间" in rendered
    assert "2026-08-11T17:30:00+08:00" in rendered


def test_triage_tab_filters_zero_zero_repositories():
    page = build_projects_page(sample_inventory())
    triage_widget = page["columns"][1]["widgets"][0]["widgets"][1]
    links = triage_widget["groups"][0]["links"]

    assert [link["title"] for link in links] == ["beta", "gamma"]


def test_replace_projects_page_removes_legacy_generated_pages():
    config = {"pages": [{"name": "ChatArch"}, {"name": "ChatArch Projects"}, {"name": "项目"}]}
    updated = replace_projects_page(config, sample_inventory())

    assert [page["name"] for page in updated["pages"]] == ["ChatArch", "项目"]


def test_replace_projects_page_keeps_projects_after_home_before_servers():
    config = {"pages": [{"name": "ChatArch"}, {"name": "服务器", "slug": "servers"}, {"name": "项目"}]}
    updated = replace_projects_page(config, sample_inventory())

    assert [page["name"] for page in updated["pages"]] == ["ChatArch", "项目", "服务器"]


def test_projects_table_cli_cell_exposes_compact_hover_tree_without_options() -> None:
    page = build_projects_page(sample_inventory())
    table_widget = page["columns"][1]["widgets"][0]["widgets"][3]
    source = table_widget["source"]

    assert "projects-cli-hover" in source
    assert "projects-cli-tree" in source
    assert "alpha" in source
    assert "projects" in source
    assert "collect" in source
    assert "render-page" in source
    assert "--help" not in source
    assert "--version" not in source
    assert "--tree" not in source
    assert "max-height" in source
    assert "overflow: auto" in source


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

    assert "hide-mountpoints-by-default" not in widget
    assert server["hide-mountpoints-by-default"] is True
    assert server["hide-swap"] is True
    assert server["mountpoints"] == {"/": {"name": "根分区", "hide": False}}
