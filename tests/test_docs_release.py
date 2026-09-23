"""Source, docs, and workflow contracts for the first bilingual docs site."""

from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
import yaml
from click.testing import CliRunner

from chatglance.cli import main


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"
URL = "https://arch.gh.wzhecnu.cn/ChatGlance/"


def test_release_metadata_and_changelog():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["urls"]["Documentation"] == URL
    docs_deps = project["optional-dependencies"]["docs"]
    for requirement in ("mkdocs>=1.6,<2", "mkdocs-material>=9.5,<10", "mkdocs-static-i18n>=1.2,<2", "mike>=2,<3"):
        assert requirement in docs_deps
    assert (ROOT / "CHANGELOG.md").read_text().startswith("# Changelog\n\n## 0.1.18 - 2026-09-23\n")


def test_site_config_bilingual_and_matched_pages():
    assert "/site/" in (ROOT / ".gitignore").read_text().splitlines()

    class SymbolicLoader(yaml.SafeLoader):
        pass

    SymbolicLoader.add_multi_constructor("tag:yaml.org,2002:python/name:", lambda loader, suffix, node: suffix)
    SymbolicLoader.add_constructor("!ENV", lambda loader, node: loader.construct_sequence(node)[1])
    config = yaml.load((ROOT / "mkdocs.yml").read_text(), Loader=SymbolicLoader)
    assert config["site_url"] == URL
    assert config["docs_dir"] == "docs/site"
    assert config["theme"]["name"] == "material"
    plugins = config["plugins"]
    i18n = next(item["i18n"] for item in plugins if isinstance(item, dict) and "i18n" in item)
    assert i18n["docs_structure"] == "suffix"
    assert i18n["fallback_to_default"] is False
    assert [language["locale"] for language in i18n["languages"]] == ["zh", "en"]
    assert {"attr_list", "md_in_html"}.issubset({extension for extension in config["markdown_extensions"] if isinstance(extension, str)})
    assert any("emoji" in str(extension) for extension in config["markdown_extensions"])
    chinese = {page.name for page in SITE.glob("*.md") if not page.name.endswith(".en.md")}
    english = {page.name.removesuffix(".en.md") + ".md" for page in SITE.glob("*.en.md")}
    assert chinese == english and {"index.md", "quickstart.md", "cli.md", "projects.md", "operations.md", "architecture.md"} <= chinese
    for page in SITE.glob("*.md"):
        text = page.read_text(encoding="utf-8")
        assert not re.search(r"/home/[^\s`]+|\brexpc\b|glance-public", text)
    for page in ("index.md", "index.en.md", "projects.md", "projects.en.md"):
        content = (SITE / page).read_text(encoding="utf-8")
        assert "ChatArch/glance" in content or page.startswith("index")
    assert not (SITE / "CNAME").exists()


def test_segmented_cli_pages_use_real_command_nodes():
    actual = CliRunner().invoke(main, ["--tree-brief"])
    assert actual.exit_code == 0
    for filename in ("cli.md", "cli.en.md"):
        sections = re.findall(r"```text\n(.*?)\n```", (SITE / filename).read_text(encoding="utf-8"), re.S)
        assert len(sections) == 3
        for section in sections:
            for line in section.splitlines()[1:]:
                command = line.split("── ", 1)[-1].strip()
                assert command in actual.output, command


def test_docs_workflows_build_and_preserve_preview():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert ".[dev,docs]" in ci and "mkdocs build --strict" in ci
    assert ci.index("python -m build") < ci.index("--force-reinstall --no-deps dist/*.whl") < ci.index("chatglance --version")
    preview = (ROOT / ".github/workflows/preview-docs.yml").read_text()
    deploy = (ROOT / ".github/workflows/deploy-docs.yml").read_text()
    preview_event = yaml.load(preview, Loader=yaml.BaseLoader)["on"]
    deploy_event = yaml.load(deploy, Loader=yaml.BaseLoader)["on"]
    assert "pull_request" in preview_event and "workflow_run" in deploy_event
    assert deploy_event["workflow_run"]["workflows"] == ["CI"]
    for workflow in (preview, deploy):
        assert ".[docs]" in workflow
        assert "mkdocs build --strict" in workflow
        assert "permissions:" in workflow and "contents: write" in workflow
        assert "keep_files: true" in workflow
        assert "gh-pages" in workflow
        assert "group: chatglance-gh-pages" in workflow and "cancel-in-progress: false" in workflow
    assert "destination_dir: dev" in preview
    assert "pull-requests: write" in preview
    assert "github.event.pull_request.head.repo.full_name == github.repository" in preview
    assert URL + "dev/" in preview
    assert "CHATGLANCE_DOCS_SITE_URL" in preview
    assert "github.paginate(github.rest.issues.listComments" in preview
    assert "destination_dir: ." in deploy
    assert "branches: [main]" in deploy
    assert "github.event.workflow_run.conclusion == 'success'" in deploy
    assert "github.event.workflow_run.event == 'push'" in deploy
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in deploy


def test_readmes_link_docs_without_claiming_publication():
    for filename in ("README.md", "README.en.md"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert URL in text
        assert "0.1.10" not in text
