from pathlib import Path


def test_ci_runs_installed_cli_and_package_gates():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    for version in ['"3.10"', '"3.11"', '"3.12"']:
        assert version in workflow
    assert "python -m pytest -q" in workflow
    assert "chatglance --version" in workflow
    assert "chatglance --tree" in workflow
    assert "chatglance --tree-brief" in workflow
    assert "python -m build" in workflow
    assert "python -m twine check dist/*" in workflow
