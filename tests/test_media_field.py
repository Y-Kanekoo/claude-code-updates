from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "check_claude_updates",
    Path(__file__).parent.parent / "scripts" / "check-claude-updates.py",
)
assert _spec is not None and _spec.loader is not None
check_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_module)

SLIDES_BASE_URL = check_module.SLIDES_BASE_URL


def test_section_fields_contains_media() -> None:
    """SECTION_FIELDS に media エントリが追加されている。"""
    ids = [entry[0] for entry in check_module.SECTION_FIELDS]
    assert "media" in ids


def test_media_entry_is_non_inline_and_omittable() -> None:
    """media は inline=False, omit_if_none=True である。"""
    media = next(e for e in check_module.SECTION_FIELDS if e[0] == "media")
    _, _, inline, omit_if_none = media
    assert inline is False
    assert omit_if_none is True


def test_slides_base_url_constant() -> None:
    """SLIDES_BASE_URL は Pages 形式の URL である。"""
    assert SLIDES_BASE_URL.startswith("https://")
    assert "github.io" in SLIDES_BASE_URL
    assert SLIDES_BASE_URL.endswith("/slides")
