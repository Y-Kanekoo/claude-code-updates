from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate_slides import preprocess_for_marp


def test_preprocess_adds_front_matter() -> None:
    """Marp YAML front matter が先頭に挿入される。"""
    source = "# タイトル\n\n### 要約\n- テスト\n"
    result = preprocess_for_marp(source)
    assert result.startswith("---\nmarp: true\n")


def test_preprocess_inserts_slide_break_before_h3() -> None:
    """### 見出しの直前にスライド区切り `---` が挿入される。"""
    source = "# タイトル\n\n### 要約\n- テスト\n\n### 判定\n- **影響度**: 中\n"
    result = preprocess_for_marp(source)
    # 少なくとも `### ` の前に `\n---\n\n` がある
    assert "\n---\n\n### 要約" in result
    assert "\n---\n\n### 判定" in result


def test_preprocess_preserves_anchor_comments() -> None:
    """HTMLアンカーコメントは保持される。"""
    source = "# タイトル\n\n<!-- section:summary -->\n### 要約\n- テスト\n"
    result = preprocess_for_marp(source)
    assert "<!-- section:summary -->" in result
