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
                "description": "Alpha connects the symbolic config schema to runtime commands.",
                "category": "python-package",
                "version": {"value": "0.1.0", "source": "pyproject.toml"},
                "cli": {
                    "commands": ["alpha"],
                    "actual_tree": {
                        "status": "ok",
                        "business_commands": ["projects", "collect", "render-page"],
                        "business_command_count": 3,
                        "global_options": ["--help", "--version", "--tree", "--tree-brief"],
                        "compact_trees": {"alpha": "alpha\n├── projects\n│   ├── collect\n│   └── render-page\n└── status"},
                        "brief_trees": {"alpha": "alpha  # Alpha CLI.\n├── projects  # Project commands.\n│   ├── collect  # Collect inventory.\n│   └── render-page  # Render page.\n└── status  # Show status."},
                        "entrypoints": {
                            "alpha": {
                                "status": "ok",
                                "business_commands": ["projects", "collect", "render-page"],
                                "business_command_count": 3,
                                "global_options": ["--help", "--version", "--tree", "--tree-brief"],
                                "brief_tree": "alpha  # Alpha CLI.\n├── projects  # Project commands.\n│   ├── collect  # Collect inventory.\n│   └── render-page  # Render page.\n└── status  # Show status.",
                            }
                        },
                    },
                },
                "docs": [{"url": "https://example.invalid/alpha"}],
                "chatenv": {
                    "depends": True,
                    "entry_points": {"alpha": "alpha.config"},
                    "schema_count": 1,
                    "field_count": 2,
                    "env_keys": ["ALPHA_API_KEY", "ALPHA_REGION"],
                    "schemas": [
                        {
                            "class_name": "AlphaConfig",
                            "title": "Alpha Configuration",
                            "storage_dir": "Alpha",
                            "aliases": ["alpha"],
                            "source_path": "src/alpha/config.py",
                            "env_keys": ["ALPHA_API_KEY", "ALPHA_REGION"],
                            "fields": [
                                {
                                    "attribute": "ALPHA_API_KEY",
                                    "env_key": "ALPHA_API_KEY",
                                    "desc": "Alpha API key.",
                                    "sensitive": True,
                                    "has_default": False,
                                },
                                {
                                    "attribute": "ALPHA_REGION",
                                    "env_key": "ALPHA_REGION",
                                    "desc": "Alpha region.",
                                    "sensitive": False,
                                    "has_default": True,
                                },
                            ],
                        }
                    ],
                },
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
                "name": "npm-mid",
                "html_url": "https://github.com/ChatArch/npm-mid",
                "open_prs": 0,
                "open_issues": 0,
                "pushed_at": "2026-08-05T00:00:00Z",
                "category": "node-package",
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
                "chatenv": {"depends": True, "entry_points": {}, "schema_count": 0, "field_count": 0, "env_keys": [], "schemas": []},
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


def test_category_tab_group_titles_include_counts_and_sorted_order():
    page = build_projects_page(sample_inventory())
    category_widget = page["columns"][1]["widgets"][0]["widgets"][2]

    assert [group["title"] for group in category_widget["groups"]] == [
        "Python 包 (1)",
        "Node / npm 包 (1)",
        "服务 / 应用 (1)",
        "文档 / 站点 (1)",
        "Python (early) (2)",
    ]


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


def test_project_category_preserves_current_category_when_actual_tree_unavailable() -> None:
    item = {
        "name": "ChatCRS",
        "category": "python-package",
        "reviewed_category": "python-early",
        "language": "Python",
        "package": {"python_name": "ChatCRS"},
        "version": {"value": "0.2.5", "source": "pypi"},
        "cli": {
            "commands": ["chatcrs"],
            "actual_tree": {
                "status": "unavailable",
                "business_commands": [],
                "business_command_count": 0,
            },
        },
        "evidence": {"has_pyproject": True},
    }

    assert category_key(item) == "python-package"
    assert display_category(item) == "Python 包"


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


def test_projects_table_uses_click_buttons_with_symbolic_detail_popovers() -> None:
    page = build_projects_page(sample_inventory())
    table_widget = page["columns"][1]["widgets"][0]["widgets"][3]
    source = table_widget["source"]

    assert table_widget["title"] == "一览表"
    assert "projects-detail-button" in source
    assert "popovertarget" in source
    assert "projects-detail-popover" in source
    assert "Alpha connects the symbolic config schema to runtime commands." in source
    assert "Env 2" in source
    assert "ALPHA_API_KEY" in source
    assert "Alpha API key." in source
    assert "敏感" in source
    assert "ChatEnv dep" not in source
    assert "未发现 ChatEnv 依赖或注册 schema" not in source


def test_projects_detail_cli_section_renders_brief_tree_code_block() -> None:
    page = build_projects_page(sample_inventory())
    source = page["columns"][1]["widgets"][0]["widgets"][3]["source"]

    assert "projects-detail-cli-tree" in source
    assert "Brief tree" in source
    assert "projects-detail-tabset" in source
    assert "projects-detail-tab-label projects-detail-tab-cli-label" in source
    assert "projects-detail-tab-label projects-detail-tab-env-label" in source
    assert "alpha  # Alpha CLI." in source
    assert "├── projects  # Project commands." in source
    assert "│   ├── collect  # Collect inventory." in source
    assert "└── status  # Show status." in source


def test_projects_table_sorts_python_first_npm_middle_and_early_last() -> None:
    page = build_projects_page(sample_inventory())
    source = page["columns"][1]["widgets"][0]["widgets"][3]["source"]

    assert source.index("alpha") < source.index("npm-mid")
    assert source.index("npm-mid") < source.index("beta")
    assert source.index("beta") < source.index("gamma")
    assert source.index("gamma") < source.index("ChatFlow")
    assert source.index("ChatFlow") < source.index("delta-template")


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
