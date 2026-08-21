from pathlib import Path
import re

from click.testing import CliRunner

from chatglance.cli import main


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _text_fences(markdown: str) -> list[str]:
    return [match.strip() for match in re.findall(r"```text\n(.*?)\n```", markdown, flags=re.DOTALL)]


def _runtime_tree(option: str) -> str:
    result = CliRunner().invoke(main, [option])
    assert result.exit_code == 0, result.output
    return result.output.strip()


def test_documented_cli_trees_match_registered_runtime_trees():
    assert _text_fences(_read("docs/cli-tree.md"))[:2] == [
        _runtime_tree("--tree"),
        _runtime_tree("--tree-brief"),
    ]


def test_readmes_and_development_guide_record_shared_cli_contract():
    for path in ["README.md", "README.en.md", "DEVELOP.md"]:
        content = _read(path)
        assert "chatglance --version" in content
        assert "chatglance --tree" in content
        assert "chatglance --tree-brief" in content
    develop = _read("DEVELOP.md")
    assert "chatstyle>=0.2.0,<0.3.0" in develop
    assert "chatenv>=0.2.10,<0.3.0" in develop
    assert "add_tree_option()" in develop
    assert "python -m twine check dist/*" in develop
    assert "include docs/cli-tree.md" in _read("MANIFEST.in")
