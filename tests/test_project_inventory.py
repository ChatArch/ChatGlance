import base64
import json

from chatglance.project_inventory import build_project_inventory, parse_click_command_names, parse_python_project_cli, _token_from_extraheader
from chatglance.projects import category_key, display_category


CHATGLANCE_CLI_SOURCE = '''
import click

@click.group(invoke_without_command=True)
def main():
    pass

@main.group()
def projects():
    pass

@projects.command("render-page")
def render_projects_page():
    pass

@projects.command(name="update-config")
def update_projects_config():
    pass
'''

ENTRYPOINT_ONLY_SOURCE = '''
import click

@click.group()
@click.version_option("0.1.0")
def main():
    pass
'''


def test_git_extraheader_token_parser_returns_secret_without_rendering_it():
    token = "test-token-value"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()

    assert _token_from_extraheader(f"Authorization: *** {encoded}") == token
    assert _token_from_extraheader(f"Authorization: Basic {encoded}") == token
    assert _token_from_extraheader(f"authorization: basic {encoded}") == token
    assert _token_from_extraheader("Authorization: Bearer ***") is None


def test_parse_click_command_names_handles_positional_and_keyword_names():
    assert parse_click_command_names(CHATGLANCE_CLI_SOURCE) == ["projects", "render-page", "update-config"]


def test_parse_python_project_cli_marks_subcommands_as_expanded():
    pyproject = {
        "project": {
            "name": "ChatGlance",
            "scripts": {"chatglance": "chatglance.cli:main"},
        }
    }

    cli = parse_python_project_cli(pyproject, fetch_file=lambda path: CHATGLANCE_CLI_SOURCE if path == "src/chatglance/cli.py" else None)

    assert cli["tree_status"] == "expanded"
    assert cli["commands"] == ["chatglance", "projects", "render-page", "update-config"]


def test_build_project_inventory_uses_fresh_cli_surface_for_categories():
    rows = [
        {
            "name": "ChatGlance",
            "full_name": "ChatArch/ChatGlance",
            "private": True,
            "open_prs": 1,
            "open_issues": 0,
            "html_url": "https://github.com/ChatArch/ChatGlance",
        },
        {
            "name": "ChatSMTP",
            "full_name": "ChatArch/ChatSMTP",
            "private": False,
            "open_prs": 0,
            "open_issues": 0,
            "html_url": "https://github.com/ChatArch/ChatSMTP",
        },
    ]
    files = {
        ("ChatArch/ChatGlance", "pyproject.toml"): '[project]\nname = "ChatGlance"\nversion = "0.1.2"\n[project.scripts]\nchatglance = "chatglance.cli:main"\n',
        ("ChatArch/ChatGlance", "src/chatglance/cli.py"): CHATGLANCE_CLI_SOURCE,
        ("ChatArch/ChatSMTP", "pyproject.toml"): '[project]\nname = "ChatSMTP"\nversion = "0.1.0"\n[project.scripts]\nchatsmtp = "chatsmtp.cli:main"\n',
        ("ChatArch/ChatSMTP", "src/chatsmtp/cli.py"): ENTRYPOINT_ONLY_SOURCE,
    }

    inventory = build_project_inventory(rows, owner="ChatArch", generated_at="2026-08-11T21:00:00+08:00", fetcher=lambda full, rel: files.get((full, rel)), workers=1)
    by_name = {item["name"]: item for item in inventory["repositories"]}

    assert inventory["generated_at"] == "2026-08-11T21:00:00+08:00"
    assert inventory["counts"]["visible_repos"] == 2
    assert inventory["counts"]["total_open_prs"] == 1
    assert category_key(by_name["ChatGlance"]) == "python-package"
    assert display_category(by_name["ChatGlance"]) == "Python 包"
    assert category_key(by_name["ChatSMTP"]) == "python-early"
    assert display_category(by_name["ChatSMTP"]) == "Python (early)"
    assert by_name["ChatGlance"]["cli"]["commands"] == ["chatglance", "projects", "render-page", "update-config"]


def test_loadable_inventory_shape_is_json_serializable(tmp_path):
    inventory = build_project_inventory([], generated_at="2026-08-11T21:00:00+08:00", fetcher=lambda _full, _rel: None, workers=1)
    output = tmp_path / "projects.json"
    output.write_text(json.dumps(inventory, ensure_ascii=False), encoding="utf-8")

    assert json.loads(output.read_text(encoding="utf-8"))["generated_at"] == "2026-08-11T21:00:00+08:00"
