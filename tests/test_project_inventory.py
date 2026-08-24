import base64
import json
import sys
import types

from chatglance import project_inventory as project_inventory_module
from chatglance.project_inventory import (
    _token_from_extraheader,
    build_project_inventory,
    make_actual_cli_tree_fetcher,
    parse_actual_cli_tree_output,
    parse_click_command_names,
    parse_python_project_cli,
    read_token_from_chatglance_chatenv,
    read_token_from_chatgh_chatenv,
    resolve_token,
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


def test_resolve_token_prefers_environment_before_repo_and_chatgh(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-token")
    monkeypatch.setattr(project_inventory_module, "read_token_from_repo_git_config", lambda: "repo-token")
    monkeypatch.setattr(project_inventory_module, "read_token_from_chatglance_chatenv", lambda: "chatglance-token")
    monkeypatch.setattr(project_inventory_module, "read_token_from_chatgh_chatenv", lambda: "chatgh-token")

    assert resolve_token(("GITHUB_TOKEN",)) == "env-token"


def test_resolve_token_prefers_repo_token_before_chatgh(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(project_inventory_module, "read_token_from_repo_git_config", lambda: "repo-token")
    monkeypatch.setattr(project_inventory_module, "read_token_from_chatglance_chatenv", lambda: "chatglance-token")
    monkeypatch.setattr(project_inventory_module, "read_token_from_chatgh_chatenv", lambda: "chatgh-token")

    assert resolve_token(("GITHUB_TOKEN",)) == "repo-token"


def test_resolve_token_prefers_chatglance_profile_before_chatgh(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(project_inventory_module, "read_token_from_repo_git_config", lambda: None)
    monkeypatch.setattr(project_inventory_module, "read_token_from_chatglance_chatenv", lambda: "chatglance-token")
    monkeypatch.setattr(project_inventory_module, "read_token_from_chatgh_chatenv", lambda: "chatgh-token")

    assert resolve_token(("GITHUB_TOKEN",)) == "chatglance-token"


def test_resolve_token_falls_back_to_chatgh_chatenv(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(project_inventory_module, "read_token_from_repo_git_config", lambda: None)
    monkeypatch.setattr(project_inventory_module, "read_token_from_chatglance_chatenv", lambda: None)
    monkeypatch.setattr(project_inventory_module, "read_token_from_chatgh_chatenv", lambda: "chatgh-token")

    assert resolve_token(("GITHUB_TOKEN",)) == "chatgh-token"


def test_read_token_from_chatglance_chatenv_uses_active_typed_store(monkeypatch):
    calls = {}

    class FakeStore:
        def __init__(self, envs_dir):
            calls["envs_dir"] = envs_dir

        def load_active(self, config_cls):
            calls["config_cls"] = config_cls.__name__
            return {"CHATGLANCE_GITHUB_TOKEN": " chatglance-token "}

    monkeypatch.setattr(project_inventory_module, "get_paths", lambda: types.SimpleNamespace(envs_dir="/safe/envs"))
    monkeypatch.setattr(project_inventory_module, "EnvStore", FakeStore)

    assert read_token_from_chatglance_chatenv() == "chatglance-token"
    assert calls == {"envs_dir": "/safe/envs", "config_cls": "ChatGlanceConfig"}


def test_read_token_from_chatgh_chatenv_loads_github_config_without_logging(monkeypatch):
    calls = {}
    chatenv_module = types.ModuleType("chatenv")
    chatenv_module.get_paths = lambda: types.SimpleNamespace(envs_dir="/safe/envs")
    chatgh_module = types.ModuleType("chatgh")
    chatgh_config_module = types.ModuleType("chatgh.config")

    class FakeTokenField:
        value = " chatgh-token "

    class FakeGitHubConfig:
        GITHUB_ACCESS_TOKEN = FakeTokenField()

        @classmethod
        def load_all(cls, envs_dir):
            calls["envs_dir"] = envs_dir

    chatgh_config_module.GitHubConfig = FakeGitHubConfig
    monkeypatch.setitem(sys.modules, "chatenv", chatenv_module)
    monkeypatch.setitem(sys.modules, "chatgh", chatgh_module)
    monkeypatch.setitem(sys.modules, "chatgh.config", chatgh_config_module)

    assert read_token_from_chatgh_chatenv() == "chatgh-token"
    assert calls == {"envs_dir": "/safe/envs"}


def test_run_chatgh_repo_list_uses_chatgh_python_api_without_shelling(monkeypatch):
    calls = []

    chatgh_module = types.ModuleType("chatgh")
    chatgh_github_module = types.ModuleType("chatgh.github")
    chatgh_commands_module = types.ModuleType("chatgh.github.commands")

    def fake_list_repos(*, owner, limit, sort, direction, token):
        calls.append({"owner": owner, "limit": limit, "sort": sort, "direction": direction, "token": token})
        return [{"name": "ChatCRS"}, {"not": "filtered"}, "ignored"]

    def fail_run(*args, **kwargs):
        raise AssertionError("run_chatgh_repo_list should import ChatGH's Python API instead of invoking chatgh CLI")

    chatgh_commands_module.list_repos = fake_list_repos
    monkeypatch.setitem(sys.modules, "chatgh", chatgh_module)
    monkeypatch.setitem(sys.modules, "chatgh.github", chatgh_github_module)
    monkeypatch.setitem(sys.modules, "chatgh.github.commands", chatgh_commands_module)
    monkeypatch.setattr(project_inventory_module, "resolve_token", lambda: "github-token")
    monkeypatch.setattr(project_inventory_module.subprocess, "run", fail_run)

    rows = project_inventory_module.run_chatgh_repo_list(owner="ChatArch", limit=10)

    assert rows == [{"name": "ChatCRS"}, {"not": "filtered"}]
    assert calls == [{"owner": "ChatArch", "limit": 10, "sort": "name", "direction": "asc", "token": "github-token"}]


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


CHATDRAW_TREE = '''
chatdraw  # ChatDraw command-line interface.
├── --help  # Show this help message.
├── --version  # Show the installed package version.
├── --tree  # Print the registered command tree.
└── hello  # Placeholder smoke command.
'''

CHATLINUX_TREE_WITH_OPTION_NODE = '''
chatlinux  # ChatLinux CLI.
├── fleet  # Manage fleet config.
│   ├── [--home TEXT]  # Override home directory.
│   ├── init  # Initialize config.
│   └── refresh  # Refresh cache.
└── status  # Show status.
'''


def test_parse_actual_cli_tree_output_counts_business_commands_not_global_options_or_placeholder_nodes():
    trivial = parse_actual_cli_tree_output(CHATCI_TREE)
    placeholder = parse_actual_cli_tree_output(CHATDRAW_TREE)
    option_node = parse_actual_cli_tree_output(CHATLINUX_TREE_WITH_OPTION_NODE)
    complex_tree = parse_actual_cli_tree_output(CHATCRS_TREE)

    assert trivial["business_command_count"] == 0
    assert trivial["global_options"] == ["--help", "--version", "--tree"]
    assert placeholder["business_command_count"] == 0
    assert placeholder["placeholder_commands"] == ["hello"]
    assert option_node["business_commands"] == ["fleet", "init", "refresh", "status"]
    assert "[--home" in option_node["global_options"]
    assert complex_tree["business_command_count"] == 8
    assert complex_tree["business_commands"] == ["health", "models", "apikey", "list", "create", "account", "list", "refresh"]
    assert "chatcrs  # HTTP/API-first CRS management helpers for ChatArch." in complex_tree["brief_tree"]
    assert "├── health  # Check CRS health." in complex_tree["brief_tree"]


def test_parse_actual_cli_tree_output_falls_back_to_help_commands_section():
    parsed = parse_actual_cli_tree_output(HELP_WITH_COMMANDS)

    assert parsed["business_command_count"] == 2
    assert parsed["business_commands"] == ["deploy", "status"]


def test_actual_cli_tree_fetcher_prefers_tree_brief(monkeypatch):
    calls = []

    def fake_run(args, check, stdout, stderr, text, timeout):
        calls.append(args)
        if args[-1] == "--tree-brief":
            return types.SimpleNamespace(returncode=0, stdout=CHATCRS_TREE)
        return types.SimpleNamespace(returncode=0, stdout="should not be used")

    monkeypatch.setattr(project_inventory_module.subprocess, "run", fake_run)

    fetch = make_actual_cli_tree_fetcher(uvx_bin="uvx")

    assert fetch("ChatCRS", "chatcrs", 30) == CHATCRS_TREE
    assert calls == [["uvx", "--from", "ChatCRS@latest", "chatcrs", "--tree-brief"]]


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
    assert by_name["ChatCI"]["category"] == "python-early"
    assert category_key(by_name["ChatCI"]) == "python-early"
    assert display_category(by_name["ChatCI"]) == "Python (early)"
    assert by_name["ChatCRS"]["cli"]["actual_tree"]["business_command_count"] == 8
    assert "chatcrs" in by_name["ChatCRS"]["cli"]["actual_tree"]["brief_trees"]
    assert "apikey" in by_name["ChatCRS"]["cli"]["actual_tree"]["brief_trees"]["chatcrs"]
    assert "# Manage CRS API keys." in by_name["ChatCRS"]["cli"]["actual_tree"]["brief_trees"]["chatcrs"]
    assert by_name["ChatCRS"]["reviewed_category"] == "python-early"
    assert by_name["ChatCRS"]["category"] == "python-package"
    assert category_key(by_name["ChatCRS"]) == "python-package"
    assert display_category(by_name["ChatCRS"]) == "Python 包"
    assert inventory["counts"]["with_actual_cli_tree"] == 2
    assert inventory["counts"]["with_actual_cli_business_commands"] == 1


def test_build_project_inventory_extracts_chatenv_schema_metadata_without_values():
    rows = [
        {
            "name": "ChatDNS",
            "full_name": "ChatArch/ChatDNS",
            "private": False,
            "open_prs": 0,
            "open_issues": 0,
            "html_url": "https://github.com/ChatArch/ChatDNS",
        }
    ]
    files = {
        (
            "ChatArch/ChatDNS",
            "pyproject.toml",
        ): """[project]
name = "ChatDNS"
dependencies = ["click>=8.0", "chatenv>=0.2.4,<0.3.0"]
[project.entry-points."chatenv.configs"]
chatdns = "chatdns.config"
""",
        (
            "ChatArch/ChatDNS",
            "src/chatdns/config.py",
        ): """from chatenv import BaseEnvConfig, EnvField

class ChatDNSConfig(BaseEnvConfig):
    _title = "ChatDNS Configuration"
    _aliases = ["chatdns", "dns"]
    _storage_dir = "ChatDNS"

    CHATDNS_PROVIDER = EnvField(
        "CHATDNS_PROVIDER",
        default="aliyun",
        desc="DNS provider selector.",
    )
    CHATDNS_TOKEN = EnvField(
        "CHATDNS_TOKEN",
        default="secret-default-should-not-render",
        desc="DNS token used for provider access.",
        is_sensitive=True,
    )
""",
    }

    inventory = build_project_inventory(
        rows,
        owner="ChatArch",
        generated_at="2026-08-21T12:00:00+08:00",
        fetcher=lambda full, rel: files.get((full, rel)),
        pypi_fetcher=lambda name: {"info": {"version": "0.1.10"}},
        workers=1,
    )
    item = inventory["repositories"][0]
    chatenv = item["chatenv"]

    assert chatenv["depends"] is True
    assert chatenv["entry_points"] == {"chatdns": "chatdns.config"}
    assert chatenv["schema_count"] == 1
    assert chatenv["field_count"] == 2
    assert chatenv["env_keys"] == ["CHATDNS_PROVIDER", "CHATDNS_TOKEN"]
    assert chatenv["schemas"][0]["storage_dir"] == "ChatDNS"
    assert chatenv["schemas"][0]["aliases"] == ["chatdns", "dns"]
    assert chatenv["schemas"][0]["fields"][1]["sensitive"] is True
    assert chatenv["schemas"][0]["fields"][1]["desc"] == "DNS token used for provider access."
    assert "secret-default-should-not-render" not in json.dumps(chatenv)
    assert inventory["counts"]["with_chatenv_dependency"] == 1
    assert inventory["counts"]["with_chatenv_entry_points"] == 1
    assert inventory["counts"]["with_chatenv_fields"] == 1


def test_loadable_inventory_shape_is_json_serializable(tmp_path):
    inventory = build_project_inventory([], generated_at="2026-08-11T21:00:00+08:00", fetcher=lambda _full, _rel: None, pypi_fetcher=lambda _name: None, workers=1)
    output = tmp_path / "projects.json"
    output.write_text(json.dumps(inventory, ensure_ascii=False), encoding="utf-8")

    assert json.loads(output.read_text(encoding="utf-8"))["generated_at"] == "2026-08-11T21:00:00+08:00"
