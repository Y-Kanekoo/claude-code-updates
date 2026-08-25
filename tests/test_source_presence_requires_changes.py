from __future__ import annotations

import pytest

from scripts.report_generation import (
    StructuredReportError,
    build_source_bullets,
    parse_structured_report,
)


def test_source_bullets_cannot_be_reported_as_no_concrete_changes() -> None:
    payload = {
        "summary": {"text": "変更記載はありません。", "source_ids": ["R1"]},
        "judgement": {
            "影響度": "要確認",
            "破壊的変更": "要確認",
            "変更記載": "具体的な変更記載なし",
            "推奨アクション": "様子見",
        },
        "highlights": [],
        "changes": [],
        "breaking_changes": [],
        "impact": [],
        "recommended_action": [],
        "notes": [],
    }

    with pytest.raises(StructuredReportError, match="変更箇条書きがある"):
        parse_structured_report(
            payload,
            build_source_bullets("- Fixed startup timeout"),
        )
