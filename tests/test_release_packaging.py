# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Release identity and Trusted Publishing regression tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

import nexus_core

ROOT = Path(__file__).resolve().parents[1]


def test_distribution_identity_matches_runtime_version() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert project["name"] == "pw-nexus-core"
    assert project["version"] == nexus_core.__version__ == "1.0.2"
    assert project["scripts"]["nexus-core"] == "nexus_core.cli:main"


def test_optional_dependencies_reference_owned_distribution() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    serialized = "\n".join(sum(project["project"]["optional-dependencies"].values(), []))
    assert "nexus-core[" not in serialized.replace("pw-nexus-core[", "")
    assert "jsonschema" in serialized


def test_install_guidance_uses_unambiguous_distribution_name() -> None:
    paths = [ROOT / "README.md", *(ROOT / "src" / "nexus_core").rglob("*.py")]

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "pip install nexus-core[" not in text, path
        assert 'pip install "nexus-core[' not in text, path


def test_public_install_guidance_uses_runtime_version_placeholder() -> None:
    expected = "pw-nexus-core[mcp]=={version}"
    for relative in (
        "src/nexus_core/app/llms_txt.py",
        "src/nexus_core/app/mcp_guide.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert expected in text, relative


def test_publish_workflow_is_tag_bound_and_tokenless() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish-pypi.yml").read_text(
        encoding="utf-8"
    )

    assert "release:\n    types: [published]" in workflow
    assert "workflow_dispatch:" in workflow
    assert "environment:\n      name: pypi" in workflow
    assert "id-token: write" in workflow
    assert "persist-credentials: false" in workflow
    assert "PYPI_TOKEN" not in workflow
    assert "password:" not in workflow
    assert "release tag must match vX.Y.Z" in workflow
    assert "python -m build --no-isolation" in workflow
    assert "setuptools==83.0.0" in workflow
    assert "wheel==0.47.0" in workflow
    assert workflow.count('test "${#artifacts[@]}" -eq 2') == 2
    assert "pw_nexus_core-${PACKAGE_VERSION}-py3-none-any.whl" in workflow
    assert 'pip install "${WHEEL}[serve]"' in workflow
    assert "Re-verify exact artifact inventory" in workflow
