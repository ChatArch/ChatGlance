import base64
import json

from chatglance.project_inventory import (
    _token_from_extraheader,
    build_project_inventory,
    parse_actual_cli_tree_output,
    parse_click_command_names,
    parse_python_project_cli,
)
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

CHATCI_TREE = '''
chatci  # ChatCI command-line interface.
├── --help  # Show this help message.
├── --version  # Show the installed package version.
└── --tree  # Print the registered command tree.
'''

CHATCRS_TREE = '''
chatcrs  # HTTP/API-first CRS management helpers for ChatArch.
├── --help  # Show this help message.
├── --version  # Show the installed package version.
├── --tree  # Print the registered command tree.
├── health  # Check CRS health.
├── models  # List available models.
├── apikey  # Manage CRS API keys.
│   ├── list  # List API keys.
│   └── create  # Create an API key.
└── account  # Manage CRS accounts.
    ├── list  # List accounts.
    └── refresh  # Refresh account state.
'''

HELP_WITH_COMMANDS = '''
Usage: sample [OPTIONS] COMMAND [ARGS]...

Options:
  --help     Show this message and exit.
  --version  Show the version and exit.

Commands:
  deploy   Deploy the service.
  status   Show status.
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


def test_parse_python_project_cli_keeps_only_package_entrypoints():
    pyproject = {
        "project": {
            "name": "ChatGlance",
            "scripts": {"chatglance": "chatglance.cli:main"},
        }
    }

    cli = parse_python_project_cli(pyproject, fetch_file=lambda path: CHATGLANCE_CLI_SOURCE if path == "src/chatglance/cli.py" else None)

    assert cli["tree_status"] == "entrypoint-only"
    assert cli["commands"] == ["chatglance"]


def test_parse_actual_cli_tree_output_counts_business_commands_not_global_options():
    trivial = parse_actual_cli_tree_output(CHATCI_TREE)
    complex_tree = parse_actual_cli_tree_output(CHATCRS_TREE)

    assert trivial["business_command_count"] == 0
    assert trivial["global_options"] == ["--help", "--version", "--tree"]
    assert complex_tree["business_command_count"] == 8
    assert complex_tree["business_commands"] == ["health", "models", "apikey", "list", "create", "account", "list", "refresh"]


def test_parse_actual_cli_tree_output_falls_back_to_help_commands_section():
    parsed = parse_actual_cli_tree_output(HELP_WITH_COMMANDS)

    assert parsed["business_command_count"] == 2
    assert parsed["business_commands"] == ["deploy", "status"]


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
    pypi = {
        "ChatGlance": {"info": {"version": "0.1.2"}},
        "ChatSMTP": {"info": {"version": "0.1.0"}},
    }
    baseline = {"repositories": [{"name": "ChatSMTP", "category": "python-package-template/early"}]}

    inventory = build_project_inventory(
        rows,
        owner="ChatArch",
        generated_at="2026-08-11T21:00:00+08:00",
        fetcher=lambda full, rel: files.get((full, rel)),
        pypi_fetcher=lambda name: pypi.get(name),
        baseline_inventory=baseline,
        workers=1,
    )
    by_name = {item["name"]: item for item in inventory["repositories"]}

    assert inventory["generated_at"] == "2026-08-11T21:00:00+08:00"
    assert inventory["counts"]["visible_repos"] == 2
    assert inventory["counts"]["total_open_prs"] == 1
    assert category_key(by_name["ChatGlance"]) == "python-package"
    assert display_category(by_name["ChatGlance"]) == "Python 包"
    assert category_key(by_name["ChatSMTP"]) == "python-early"
    assert display_category(by_name["ChatSMTP"]) == "Python (early)"
    assert by_name["ChatGlance"]["cli"]["commands"] == ["chatglance"]
    assert by_name["ChatGlance"]["version"] == {"value": "0.1.2", "source": "pypi"}
    assert by_name["ChatSMTP"]["version"] == {"value": "0.1.0", "source": "pypi"}
    assert inventory["counts"]["with_detected_cli_entries"] == 2


def test_build_project_inventory_classifies_from_actual_cli_tree_over_stale_override():
    rows = [
        {"name": "ChatCI", "full_name": "ChatArch/ChatCI", "open_prs": 0, "open_issues": 0},
        {"name": "ChatCRS", "full_name": "ChatArch/ChatCRS", "open_prs": 0, "open_issues": 0},
    ]
    files = {
        ("ChatArch/ChatCI", "pyproject.toml"): '[project]\nname = "ChatCI"\ndescription = "ChatCI: ChatArch placeholder package for PyPI name registration."\n[project.scripts]\nchatci = "chatci.cli:main"\n',
        ("ChatArch/ChatCRS", "pyproject.toml"): '[project]\nname = "ChatCRS"\ndescription = "HTTP/API-first CRS management helpers for ChatArch."\n[project.scripts]\nchatcrs = "chatcrs.cli:main"\n',
    }
    pypi = {
        "ChatCI": {"info": {"version": "0.1.1"}},
        "ChatCRS": {"info": {"version": "0.2.6"}},
    }
    cli_trees = {("ChatCI", "chatci"): CHATCI_TREE, ("ChatCRS", "chatcrs"): CHATCRS_TREE}
    baseline = {"repositories": [{"name": "ChatCRS", "category": "python-early"}]}

    inventory = build_project_inventory(
        rows,
        owner="ChatArch",
        generated_at="2026-08-12T01:30:00+08:00",
        fetcher=lambda full, rel: files.get((full, rel)),
        pypi_fetcher=lambda name: pypi.get(name),
        actual_cli_tree_fetcher=lambda package, command, timeout=90: cli_trees.get((package, command)),
        baseline_inventory=baseline,
        workers=1,
    )
    by_name = {item["name"]: item for item in inventory["repositories"]}

    assert by_name["ChatCI"]["cli"]["actual_tree"]["business_command_count"] == 0
    assert category_key(by_name["ChatCI"]) == "python-early"
    assert display_category(by_name["ChatCI"]) == "Python (early)"
    assert by_name["ChatCRS"]["cli"]["actual_tree"]["business_command_count"] == 8
    assert category_key(by_name["ChatCRS"]) == "python-package"
    assert display_category(by_name["ChatCRS"]) == "Python 包"
    assert inventory["counts"]["with_actual_cli_tree"] == 2
    assert inventory["counts"]["with_actual_cli_business_commands"] == 1


def test_loadable_inventory_shape_is_json_serializable(tmp_path):
    inventory = build_project_inventory([], generated_at="2026-08-11T21:00:00+08:00", fetcher=lambda _full, _rel: None, pypi_fetcher=lambda _name: None, workers=1)
    output = tmp_path / "projects.json"
    output.write_text(json.dumps(inventory, ensure_ascii=False), encoding="utf-8")

    assert json.loads(output.read_text(encoding="utf-8"))["generated_at"] == "2026-08-11T21:00:00+08:00"
