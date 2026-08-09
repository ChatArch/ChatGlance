from pathlib import Path

import yaml


def test_publish_workflow_is_tag_only_oidc_release():
    workflow = yaml.safe_load(Path(".github/workflows/publish.yml").read_text())

    triggers = workflow[True]
    assert "workflow_dispatch" not in triggers
    assert triggers == {"push": {"tags": ["v*"]}}

    publish_job = workflow["jobs"]["publish"]
    assert publish_job["permissions"]["id-token"] == "write"
    assert publish_job["permissions"]["contents"] == "read"
    assert "environment" not in publish_job

    text = Path(".github/workflows/publish.yml").read_text()
    assert "PYPI_API_TOKEN" not in text
    assert "TWINE_PASSWORD" not in text
    assert "secrets.PYPI" not in text
    assert "PACKAGE_NAME: \"ChatGlance\"" in text
