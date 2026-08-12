from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generate_slides import preprocess_for_marp, validate_slide_budget
from scripts.report_schema import validate_canonical_report

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports" / "claude-code"

SPEC = importlib.util.spec_from_file_location(
    "generate_index_for_corpus", ROOT / "scripts" / "generate-index.py"
)
assert SPEC is not None and SPEC.loader is not None
INDEX_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INDEX_MODULE)


def _report_files() -> list[Path]:
    return sorted(
        path
        for path in REPORTS_DIR.glob("*.md")
        if path.name != "index.md"
    )


def test_report_corpus_is_canonical() -> None:
    failures: dict[str, list[str]] = {}
    for report_path in _report_files():
        errors = validate_canonical_report(
            report_path.read_text(encoding="utf-8"),
            filename=report_path.name,
        )
        if errors:
            failures[report_path.name] = errors

    assert failures == {}


def test_index_contains_every_report_once_in_semver_order() -> None:
    index_data = json.loads((REPORTS_DIR / "index.json").read_text(encoding="utf-8"))
    releases = index_data["releases"]
    indexed_files = [release["file"] for release in releases]
    expected_files = [path.name for path in _report_files()]

    assert len(indexed_files) == len(set(indexed_files)) == len(expected_files)
    assert set(indexed_files) == set(expected_files)
    versions = [release["version"] for release in releases]
    assert versions == sorted(
        versions,
        key=INDEX_MODULE._version_tuple,
        reverse=True,
    )


def test_every_report_builds_budgeted_slides() -> None:
    failures: dict[str, list[str]] = {}
    for report_path in _report_files():
        slides = preprocess_for_marp(report_path.read_text(encoding="utf-8"))
        errors = validate_slide_budget(slides)
        if errors:
            failures[report_path.name] = errors

    assert failures == {}
