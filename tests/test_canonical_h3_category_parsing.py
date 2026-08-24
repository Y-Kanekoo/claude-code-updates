from __future__ import annotations

from scripts.report_generation import (
    build_source_bullets,
    build_source_fallback_report,
    render_summary_markdown,
)
from scripts.report_schema import parse_sections


def test_canonical_other_category_remains_inside_changes_section() -> None:
    sources = build_source_bullets("- Bug fixes and reliability improvements")
    markdown = render_summary_markdown(build_source_fallback_report(sources))

    sections = parse_sections(markdown)

    assert "### その他" in sections["changes"]
    assert "Bug fixes and reliability improvements" in sections["changes"]


def test_unanchored_legacy_h3_section_remains_readable() -> None:
    sections = parse_sections("### バグ修正\n\n- Fixed startup timeout")

    assert sections["changes"] == "- Fixed startup timeout"
