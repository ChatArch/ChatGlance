from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat

from click.testing import CliRunner
import pytest
import yaml

from chatglance.access import build_public_glance_config, project_public_inventory
from chatglance.cli import main
from chatglance.projects import build_projects_page


PRIVATE_MARKERS = (
    "SecretVault",
    "https://github.com/ChatArch/SecretVault",
    "private implementation details",
    "secretctl",
    "SECRET_VAULT_TOKEN",
)


def full_inventory() -> dict:
    return {
        "generated_at": "2026-09-23T09:30:00+08:00",
        "source": {
            "owner": "ChatArch",
            "repo_count": 2,
            "original_row_count": 2,
            "auth_source": "private token",
            "notes": "SecretVault was included in the authenticated collection",
        },
        "counts": {
            "visible_repos": 999,
            "public": 999,
            "private": 999,
            "total_open_prs": 999,
        },
        "categories": {"python-package": 999, "service/app": 999},
        "internal_summary": "SecretVault private implementation details",
        "repositories": [
            {
                "name": "OpenTools",
                "full_name": "ChatArch/OpenTools",
                "private": False,
                "archived": False,
                "html_url": "https://github.com/ChatArch/OpenTools",
                "description": "Public tools for ChatArch users.",
                "open_prs": 2,
                "open_issues": 1,
                "pushed_at": "2026-09-22T00:00:00Z",
                "category": "python-package",
                "version": {"value": "1.2.3", "source": "pypi"},
                "cli": {
                    "commands": ["opentools"],
                    "actual_tree": {
                        "status": "ok",
                        "business_command_count": 1,
                        "business_commands": ["status"],
                    },
                },
                "chatenv": {
                    "depends": True,
                    "entry_points": {"opentools": "opentools.config"},
                    "field_count": 1,
                    "schemas": [
                        {
                            "class_name": "OpenToolsConfig",
                            "fields": [
                                {
                                    "env_key": "OPENTOOLS_REGION",
                                    "desc": "Public region selector.",
                                    "sensitive": False,
                                    "has_default": True,
                                }
                            ],
                        }
                    ],
                },
                "docs": [{"url": "https://docs.example.invalid/opentools"}],
            },
            {
                "name": "SecretVault",
                "full_name": "ChatArch/SecretVault",
                "private": True,
                "archived": True,
                "html_url": "https://github.com/ChatArch/SecretVault",
                "description": "private implementation details",
                "open_prs": 7,
                "open_issues": 9,
                "pushed_at": "2026-09-23T00:00:00Z",
                "category": "service/app",
                "version": {"value": "9.9.9", "source": "private-manifest"},
                "cli": {"commands": ["secretctl", "rotate-master-key"]},
                "chatenv": {
                    "depends": True,
                    "entry_points": {"secret": "secret.config"},
                    "field_count": 1,
                    "schemas": [
                        {
                            "class_name": "SecretConfig",
                            "fields": [
                                {
                                    "env_key": "SECRET_VAULT_TOKEN",
                                    "desc": "private credential metadata",
                                    "sensitive": True,
                                    "has_default": False,
                                }
                            ],
                        }
                    ],
                },
                "docs": [{"url": "https://private.example.invalid/secret-vault"}],
            },
        ],
    }


def full_config() -> dict:
    return {
        "auth": {"secret-key": "do-not-publish", "users": {"admin": {"password": "hash"}}},
        "server": {"host": "10.0.0.9", "port": 8080},
        "theme": {"background-color": "12 12 12"},
        "pages": [
            {
                "name": "ChatArch",
                "columns": [
                    {
                        "size": "full",
                        "widgets": [
                            {"type": "server-stats"},
                            {"type": "monitor", "url": "https://private-monitor.invalid"},
                            {"type": "repository", "repository": "ChatArch/SecretVault"},
                            {"type": "rss", "url": "https://private-feed.invalid"},
                        ],
                    }
                ],
            },
            {"name": "项目", "columns": [{"size": "full", "widgets": [{"type": "html", "source": "SecretVault"}]}]},
            {"name": "ChatArch Projects"},
            {"name": "网站服务"},
            {"name": "Sites"},
            {"name": "订阅详情"},
            {"name": "Account Limits"},
            {"name": "服务器"},
            {"name": "Servers"},
        ],
    }


def test_public_inventory_projection_is_detached_fail_closed_and_recomputes_derivatives() -> None:
    source = full_inventory()
    before = deepcopy(source)

    public = project_public_inventory(source)

    assert source == before
    assert public is not source
    assert [row["name"] for row in public["repositories"]] == ["OpenTools"]
    assert "private" not in public["repositories"][0]
    assert public["counts"]["visible_repos"] == 1
    assert public["counts"]["public"] == 1
    assert public["counts"]["total_open_prs"] == 2
    assert public["counts"]["total_open_issues"] == 1
    assert public["counts"]["with_detected_version"] == 1
    assert "with_detected_cli_entries" not in public["counts"]
    assert "with_chatenv_fields" not in public["counts"]
    assert "with_actual_cli_tree" not in public["counts"]
    assert "private" not in public["counts"]
    assert public["categories"] == {"python-package": 1}
    assert "source" not in public
    assert "internal_summary" not in public

    rendered = json.dumps(public, ensure_ascii=False)
    for marker in PRIVATE_MARKERS:
        assert marker not in rendered

    public["repositories"][0]["docs"][0]["url"] = "https://changed.invalid"
    assert source["repositories"][0]["docs"][0]["url"] == "https://docs.example.invalid/opentools"


def test_projection_requires_an_explicit_false_private_flag() -> None:
    source = full_inventory()
    source["repositories"].append(
        {
            "name": "UnknownVisibility",
            "html_url": "https://github.com/ChatArch/UnknownVisibility",
            "category": "other",
        }
    )

    public = project_public_inventory(source)

    assert [row["name"] for row in public["repositories"]] == ["OpenTools"]


def test_public_projection_uses_an_explicit_nested_allowlist() -> None:
    source = full_inventory()
    public_row = source["repositories"][0]
    public_row.update(
        {
            "owner": "SECRET_ROW_OWNER",
            "collector": {"token_hint": "SECRET_COLLECTOR_METADATA"},
            "evidence": {"manifest": "SECRET_EVIDENCE_PATH"},
            "package": {"private_registry": "SECRET_PACKAGE_REGISTRY"},
            "arbitrary": {"nested": ["SECRET_ARBITRARY_FIELD"]},
            "web": {
                "url": "https://public.example.invalid/app",
                "kind": "app",
                "internal_label": "SECRET_WEB_METADATA",
            },
        }
    )
    public_row["version"]["manifest_path"] = "SECRET_VERSION_METADATA"
    public_row["docs"][0]["source"] = "SECRET_DOCS_METADATA"

    public = project_public_inventory(source)

    row = public["repositories"][0]
    assert set(row) <= {
        "name",
        "html_url",
        "description",
        "open_prs",
        "open_issues",
        "pushed_at",
        "updated_at",
        "category",
        "version",
        "docs",
        "web",
    }
    assert {"name", "html_url", "description", "open_prs", "open_issues", "category"} <= set(row)
    assert set(row["version"]) <= {"value", "source"}
    assert all(set(candidate) == {"url"} for candidate in row["docs"])
    assert row["web"] == {"url": "https://public.example.invalid/app", "kind": "app"}
    assert "full_name" not in row
    assert "cli" not in row
    assert "chatenv" not in row
    rendered = json.dumps(public, ensure_ascii=False)
    for marker in (
        "SECRET_ROW_OWNER",
        "SECRET_COLLECTOR_METADATA",
        "SECRET_EVIDENCE_PATH",
        "SECRET_PACKAGE_REGISTRY",
        "SECRET_ARBITRARY_FIELD",
        "SECRET_VERSION_METADATA",
        "SECRET_DOCS_METADATA",
        "SECRET_WEB_METADATA",
        "OPENTOOLS_REGION",
    ):
        assert marker not in rendered


def test_all_private_projection_omits_source_and_private_derived_metadata() -> None:
    source = full_inventory()
    source["repositories"] = [source["repositories"][1]]
    source["source"]["owner"] = "SECRET_SOURCE_OWNER"
    source["source"]["collector"] = {"credential_hint": "SECRET_SOURCE_METADATA"}

    public = project_public_inventory(source)

    assert public["repositories"] == []
    assert public["counts"]["visible_repos"] == 0
    assert public["categories"] == {}
    assert "source" not in public
    public_config = build_public_glance_config(full_config(), source)
    rendered = json.dumps(public, ensure_ascii=False) + yaml.safe_dump(public_config, allow_unicode=True)
    for marker in ("SecretVault", "SECRET_SOURCE_OWNER", "SECRET_SOURCE_METADATA", "private token"):
        assert marker not in rendered


def test_private_and_public_project_audiences_have_distinct_visibility_contracts() -> None:
    inventory = full_inventory()

    default_page = build_projects_page(inventory)
    private_page = build_projects_page(inventory, audience="private")
    assert default_page == private_page

    private_source = private_page["columns"][1]["widgets"][0]["widgets"][3]["source"]
    assert "<th>可见性</th>" in private_source
    open_row = next(fragment for fragment in private_source.split("<tr>") if ">OpenTools</a>" in fragment)
    secret_row = next(fragment for fragment in private_source.split("<tr>") if ">SecretVault</a>" in fragment)
    assert "Public" in open_row
    assert "Private" in secret_row
    open_detail = next(fragment for fragment in private_source.split("<article") if "OpenTools 详情" in fragment)
    secret_detail = next(fragment for fragment in private_source.split("<article") if "SecretVault 详情" in fragment)
    assert "可见性" in open_detail and "Public" in open_detail
    assert "可见性" in secret_detail and "Private" in secret_detail

    public_page = build_projects_page(inventory, audience="public")
    public_source = public_page["columns"][1]["widgets"][0]["widgets"][3]["source"]
    public_yaml = yaml.safe_dump(public_page, allow_unicode=True, sort_keys=False)
    assert "<th>可见性</th>" not in public_source
    assert "projects-visibility" not in public_source
    assert ">Public<" not in public_source
    assert ">Private<" not in public_source
    for marker in PRIVATE_MARKERS:
        assert marker not in public_yaml


def test_public_renderer_does_not_treat_a_projected_artifact_as_full_inventory() -> None:
    projected = project_public_inventory(full_inventory())

    page = build_projects_page(projected, audience="public")

    rendered = yaml.safe_dump(page, allow_unicode=True, sort_keys=False)
    assert "OpenTools" not in rendered
    for marker in PRIVATE_MARKERS:
        assert marker not in rendered


def test_public_renderer_projects_from_full_inventory_at_the_render_boundary() -> None:
    page = build_projects_page(full_inventory(), audience="public")

    rendered = yaml.safe_dump(page, allow_unicode=True, sort_keys=False)
    assert "OpenTools" in rendered
    for marker in PRIVATE_MARKERS:
        assert marker not in rendered
    assert "<code>opentools</code>" not in rendered
    assert "OPENTOOLS_REGION" not in rendered


def test_public_renderer_does_not_trust_a_forged_projected_inventory() -> None:
    forged = project_public_inventory(full_inventory())
    forged_row = forged["repositories"][0]
    forged_row.update(
        {
            "name": "SecretVault",
            "full_name": "ChatArch/SecretVault",
            "html_url": "https://github.com/ChatArch/SecretVault",
            "description": "private implementation details",
            "cli": {"commands": ["secretctl"]},
            "chatenv": {"schemas": [{"fields": [{"env_key": "SECRET_VAULT_TOKEN"}]}]},
        }
    )

    page = build_projects_page(forged, audience="public")

    rendered = yaml.safe_dump(page, allow_unicode=True, sort_keys=False)
    for marker in PRIVATE_MARKERS:
        assert marker not in rendered


def test_public_config_passes_full_inventory_through_the_render_boundary() -> None:
    public = build_public_glance_config(full_config(), full_inventory())

    rendered = yaml.safe_dump(public, allow_unicode=True, sort_keys=False)
    assert "OpenTools" in rendered
    for marker in PRIVATE_MARKERS:
        assert marker not in rendered


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "javascript:alert(unsafe-marker)",
        "data:text/html,unsafe-marker",
        "https://user:unsafe-marker@example.com/repository",
        "https://[::1/unsafe-marker",
        "https://[::1]/unsafe-marker",
        "https://127.0.0.1/unsafe-marker",
        "https://10.23.45.67/unsafe-marker",
        "https://localhost/unsafe-marker",
        "https://service.local/unsafe-marker",
    ],
)
def test_unsafe_repository_and_docs_urls_are_absent_from_both_audiences(unsafe_url: str) -> None:
    inventory = full_inventory()
    inventory["repositories"][0]["html_url"] = unsafe_url
    inventory["repositories"][0]["docs"] = [{"url": unsafe_url}]

    for audience in ("private", "public"):
        page = build_projects_page(inventory, audience=audience)
        table_source = page["columns"][1]["widgets"][0]["widgets"][3]["source"]
        rendered = yaml.safe_dump(page, allow_unicode=True, sort_keys=False)
        assert "unsafe-marker" not in table_source
        assert "unsafe-marker" not in rendered


@pytest.mark.parametrize("visibility", [None, "false", 0, 1, {}, []])
def test_malformed_visibility_is_unknown_in_authenticated_rendering(visibility) -> None:
    inventory = full_inventory()
    inventory["repositories"][0]["private"] = visibility

    page = build_projects_page(inventory)

    source = page["columns"][1]["widgets"][0]["widgets"][3]["source"]
    row = next(fragment for fragment in source.split("<tr>") if ">OpenTools</a>" in fragment)
    detail = next(fragment for fragment in source.split("<article") if "OpenTools 详情" in fragment)
    assert "Unknown" in row
    assert "Unknown" in detail
    assert ">Public<" not in row
    assert ">Public<" not in detail


def test_missing_visibility_is_unknown_in_authenticated_rendering() -> None:
    inventory = full_inventory()
    inventory["repositories"][0].pop("private")

    page = build_projects_page(inventory)

    source = page["columns"][1]["widgets"][0]["widgets"][3]["source"]
    row = next(fragment for fragment in source.split("<tr>") if ">OpenTools</a>" in fragment)
    assert "Unknown" in row
    assert ">Public<" not in row


def test_public_config_is_detached_minimal_and_contains_only_public_pages() -> None:
    config = full_config()
    inventory = full_inventory()
    config_before = deepcopy(config)
    inventory_before = deepcopy(inventory)
    public = build_public_glance_config(config, inventory)

    assert config == config_before
    assert inventory == inventory_before
    assert "auth" not in public
    assert "server" not in public
    assert [page["name"] for page in public["pages"]] == ["ChatArch", "项目"]
    home = public["pages"][0]
    home_types = {
        widget["type"]
        for column in home["columns"]
        for widget in column.get("widgets", [])
    }
    assert home_types <= {"bookmarks", "html"}
    assert home_types.isdisjoint({"server-stats", "monitor", "repository", "rss"})

    rendered = yaml.safe_dump(public, allow_unicode=True, sort_keys=False)
    assert "公开项目" in rendered
    assert "https://github.com/ChatArch" in rendered
    assert "可见性" not in rendered
    assert "Private" not in rendered
    for marker in PRIVATE_MARKERS:
        assert marker not in rendered

    public["pages"][0]["name"] = "changed"
    assert config["pages"][0]["name"] == "ChatArch"


def test_public_home_bookmark_uses_exact_projects_slug_route() -> None:
    public = build_public_glance_config(full_config(), full_inventory())
    home_links = [
        link
        for column in public["pages"][0]["columns"]
        for widget in column["widgets"]
        if widget["type"] == "bookmarks"
        for group in widget["groups"]
        for link in group["links"]
    ]

    projects_link = next(link for link in home_links if link["title"] == "公开项目")

    assert projects_link["url"] == "/projects"


def test_public_config_accepts_only_an_explicit_valid_server_mapping() -> None:
    server = {"host": "0.0.0.0", "port": 9090}

    public = build_public_glance_config(full_config(), full_inventory(), server=server)

    assert public["server"] == server
    assert public["server"] is not server


@pytest.mark.parametrize(
    "server",
    [
        {},
        {"host": "0.0.0.0"},
        {"port": 9090},
        {"host": "0.0.0.0", "port": 9090, "auth": "secret"},
        {"host": " https://example.invalid", "port": 9090},
        {"host": "https://example.invalid", "port": 9090},
        {"host": "bad host", "port": 9090},
        {"host": "0.0.0.0", "port": True},
        {"host": "0.0.0.0", "port": "9090"},
        {"host": "0.0.0.0", "port": 0},
        {"host": "0.0.0.0", "port": 65536},
    ],
)
def test_invalid_public_server_mapping_is_rejected(server: dict) -> None:
    with pytest.raises(ValueError, match="public server"):
        build_public_glance_config(full_config(), full_inventory(), server=server)


def test_access_cli_writes_safe_candidates_and_reports_only_safe_paths_and_counts(tmp_path) -> None:
    config_path = tmp_path / "private.yml"
    inventory_path = tmp_path / "private.json"
    config_output = tmp_path / "candidate" / "public.yml"
    inventory_output = tmp_path / "candidate" / "public.json"
    config_output.parent.mkdir()
    config_path.write_text(yaml.safe_dump(full_config(), allow_unicode=True), encoding="utf-8")
    inventory_path.write_text(json.dumps(full_inventory(), ensure_ascii=False), encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "access",
            "render-public",
            "--config",
            str(config_path),
            "--inventory",
            str(inventory_path),
            "--config-output",
            str(config_output),
            "--inventory-output",
            str(inventory_output),
            "--host",
            "127.0.0.1",
            "--port",
            "9090",
        ],
    )

    assert result.exit_code == 0, result.output
    assert f"config={config_output}" in result.output
    assert f"inventory={inventory_output}" in result.output
    assert "repos=1" in result.output
    assert "pages=2" in result.output
    assert "private=" not in result.output
    public_inventory = json.loads(inventory_output.read_text(encoding="utf-8"))
    public_config = yaml.safe_load(config_output.read_text(encoding="utf-8"))
    assert [row["name"] for row in public_inventory["repositories"]] == ["OpenTools"]
    assert public_config["server"] == {"host": "127.0.0.1", "port": 9090}
    assert stat.S_IMODE(config_output.stat().st_mode) == 0o600
    assert stat.S_IMODE(inventory_output.stat().st_mode) == 0o600
    combined = inventory_output.read_text(encoding="utf-8") + config_output.read_text(encoding="utf-8")
    for marker in PRIVATE_MARKERS:
        assert marker not in combined


def test_access_cli_rejects_invalid_server_before_creating_either_output(tmp_path) -> None:
    config_path = tmp_path / "private.yml"
    inventory_path = tmp_path / "private.json"
    config_output = tmp_path / "candidate" / "public.yml"
    inventory_output = tmp_path / "candidate" / "public.json"
    config_output.parent.mkdir()
    config_path.write_text(yaml.safe_dump(full_config(), allow_unicode=True), encoding="utf-8")
    inventory_path.write_text(json.dumps(full_inventory(), ensure_ascii=False), encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "access",
            "render-public",
            "--config",
            str(config_path),
            "--inventory",
            str(inventory_path),
            "--config-output",
            str(config_output),
            "--inventory-output",
            str(inventory_output),
            "--host",
            "https://bad-host.invalid",
            "--port",
            "9090",
        ],
    )

    assert result.exit_code != 0
    assert "public server" in result.output
    assert not config_output.exists()
    assert not inventory_output.exists()


def test_access_cli_rejects_invalid_yaml_without_echoing_input_or_creating_outputs(tmp_path) -> None:
    config_path = tmp_path / "invalid.yml"
    inventory_path = tmp_path / "private.json"
    config_output = tmp_path / "candidate" / "public.yml"
    inventory_output = tmp_path / "candidate" / "public.json"
    config_output.parent.mkdir()
    config_path.write_text("auth: DO_NOT_ECHO\npages: [\n", encoding="utf-8")
    inventory_path.write_text(json.dumps(full_inventory(), ensure_ascii=False), encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "access",
            "render-public",
            "--config",
            str(config_path),
            "--inventory",
            str(inventory_path),
            "--config-output",
            str(config_output),
            "--inventory-output",
            str(inventory_output),
        ],
    )

    assert result.exit_code != 0
    assert "invalid Glance YAML" in result.output
    assert "DO_NOT_ECHO" not in result.output
    assert not config_output.exists()
    assert not inventory_output.exists()


def test_access_cli_rejects_invalid_json_without_echoing_input_or_creating_outputs(tmp_path) -> None:
    config_path = tmp_path / "private.yml"
    inventory_path = tmp_path / "invalid.json"
    output_dir = tmp_path / "candidate"
    output_dir.mkdir()
    config_output = output_dir / "public.yml"
    inventory_output = output_dir / "public.json"
    config_path.write_text(yaml.safe_dump(full_config(), allow_unicode=True), encoding="utf-8")
    inventory_path.write_text('{"token":"DO_NOT_ECHO",', encoding="utf-8")

    result = _invoke_render_public(config_path, inventory_path, config_output, inventory_output)

    assert result.exit_code != 0
    assert "invalid project inventory JSON" in result.output
    assert "DO_NOT_ECHO" not in result.output
    assert not config_output.exists()
    assert not inventory_output.exists()


def _access_inputs(tmp_path: Path) -> tuple[Path, Path]:
    config_path = tmp_path / "private.yml"
    inventory_path = tmp_path / "private.json"
    config_path.write_text(yaml.safe_dump(full_config(), allow_unicode=True), encoding="utf-8")
    inventory_path.write_text(json.dumps(full_inventory(), ensure_ascii=False), encoding="utf-8")
    return config_path, inventory_path


def _invoke_render_public(
    config_path: Path,
    inventory_path: Path,
    config_output: Path,
    inventory_output: Path,
):
    return CliRunner().invoke(
        main,
        [
            "access",
            "render-public",
            "--config",
            str(config_path),
            "--inventory",
            str(inventory_path),
            "--config-output",
            str(config_output),
            "--inventory-output",
            str(inventory_output),
        ],
    )


def test_access_cli_rejects_same_candidate_path_before_writing(tmp_path) -> None:
    config_path, inventory_path = _access_inputs(tmp_path)
    output_dir = tmp_path / "candidate"
    output_dir.mkdir()
    output = output_dir / "public-candidate"

    result = _invoke_render_public(config_path, inventory_path, output, output)

    assert result.exit_code != 0
    assert "distinct" in result.output
    assert not output.exists()


def test_access_cli_rejects_a_candidate_that_aliases_an_input(tmp_path) -> None:
    config_path, inventory_path = _access_inputs(tmp_path)
    original_config = config_path.read_bytes()
    inventory_output = tmp_path / "public.json"

    result = _invoke_render_public(config_path, inventory_path, config_path, inventory_output)

    assert result.exit_code != 0
    assert "distinct" in result.output
    assert config_path.read_bytes() == original_config
    assert not inventory_output.exists()


def test_access_cli_rejects_a_symlink_candidate_without_following_it(tmp_path) -> None:
    config_path, inventory_path = _access_inputs(tmp_path)
    output_dir = tmp_path / "candidate"
    output_dir.mkdir()
    secret_marker = "TOKEN_DO_NOT_DISCLOSE"
    victim = tmp_path / secret_marker
    victim.write_text("original victim\n", encoding="utf-8")
    config_output = output_dir / "public.yml"
    inventory_output = output_dir / "public.json"
    config_output.symlink_to(victim)

    result = _invoke_render_public(config_path, inventory_path, config_output, inventory_output)

    assert result.exit_code != 0
    assert "Error:" in result.output
    assert secret_marker not in result.output
    assert victim.read_text(encoding="utf-8") == "original victim\n"
    assert config_output.is_symlink()
    assert not inventory_output.exists()


def test_access_cli_rejects_a_symlink_output_directory(tmp_path) -> None:
    config_path, inventory_path = _access_inputs(tmp_path)
    real_output_dir = tmp_path / "real-candidate"
    real_output_dir.mkdir()
    linked_output_dir = tmp_path / "candidate"
    linked_output_dir.symlink_to(real_output_dir, target_is_directory=True)
    config_output = linked_output_dir / "public.yml"
    inventory_output = linked_output_dir / "public.json"

    result = _invoke_render_public(config_path, inventory_path, config_output, inventory_output)

    assert result.exit_code != 0
    assert "Error:" in result.output
    assert list(real_output_dir.iterdir()) == []


@pytest.mark.parametrize("parent_kind", ["missing", "file"])
def test_access_cli_rejects_an_invalid_output_parent_without_partial_files(tmp_path, parent_kind: str) -> None:
    config_path, inventory_path = _access_inputs(tmp_path)
    output_dir = tmp_path / "TOKEN_INVALID_PARENT"
    if parent_kind == "file":
        output_dir.write_text("not a directory", encoding="utf-8")
    config_output = output_dir / "public.yml"
    inventory_output = output_dir / "public.json"

    result = _invoke_render_public(config_path, inventory_path, config_output, inventory_output)

    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "TOKEN_INVALID_PARENT" not in result.output
    assert not config_output.exists()
    assert not inventory_output.exists()


def test_access_cli_requires_candidates_to_share_one_safe_directory(tmp_path) -> None:
    config_path, inventory_path = _access_inputs(tmp_path)
    config_dir = tmp_path / "config-candidate"
    inventory_dir = tmp_path / "inventory-candidate"
    config_dir.mkdir()
    inventory_dir.mkdir()
    config_output = config_dir / "public.yml"
    inventory_output = inventory_dir / "public.json"

    result = _invoke_render_public(config_path, inventory_path, config_output, inventory_output)

    assert result.exit_code != 0
    assert "same directory" in result.output
    assert not config_output.exists()
    assert not inventory_output.exists()


@pytest.mark.parametrize("existing", [False, True])
def test_access_cli_rolls_back_the_pair_when_the_second_publish_fails(
    tmp_path,
    monkeypatch,
    existing: bool,
) -> None:
    config_path, inventory_path = _access_inputs(tmp_path)
    output_dir = tmp_path / "candidate"
    output_dir.mkdir()
    config_output = output_dir / "public.yml"
    inventory_output = output_dir / "public.json"
    if existing:
        config_output.write_text("old config\n", encoding="utf-8")
        inventory_output.write_text("old inventory\n", encoding="utf-8")

    real_replace = os.replace
    publication_targets: list[Path] = []

    def fail_second_publication(source, target):
        target_path = Path(target)
        if target_path in {config_output, inventory_output}:
            publication_targets.append(target_path)
            if len(publication_targets) == 2:
                raise OSError("token=SECRET_SECOND_WRITE_FAILURE")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", fail_second_publication)

    result = _invoke_render_public(config_path, inventory_path, config_output, inventory_output)

    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "SECRET_SECOND_WRITE_FAILURE" not in result.output
    if existing:
        assert config_output.read_text(encoding="utf-8") == "old config\n"
        assert inventory_output.read_text(encoding="utf-8") == "old inventory\n"
        assert set(output_dir.iterdir()) == {config_output, inventory_output}
    else:
        assert list(output_dir.iterdir()) == []


def test_access_cli_atomically_replaces_regular_candidates_with_mode_0600(tmp_path) -> None:
    config_path, inventory_path = _access_inputs(tmp_path)
    output_dir = tmp_path / "candidate"
    output_dir.mkdir()
    config_output = output_dir / "public.yml"
    inventory_output = output_dir / "public.json"
    config_output.write_text("old config\n", encoding="utf-8")
    inventory_output.write_text("old inventory\n", encoding="utf-8")
    config_output.chmod(0o644)
    inventory_output.chmod(0o644)

    result = _invoke_render_public(config_path, inventory_path, config_output, inventory_output)

    assert result.exit_code == 0, result.output
    assert yaml.safe_load(config_output.read_text(encoding="utf-8"))["pages"]
    assert json.loads(inventory_output.read_text(encoding="utf-8"))["repositories"]
    assert stat.S_IMODE(config_output.stat().st_mode) == 0o600
    assert stat.S_IMODE(inventory_output.stat().st_mode) == 0o600
    assert set(output_dir.iterdir()) == {config_output, inventory_output}
