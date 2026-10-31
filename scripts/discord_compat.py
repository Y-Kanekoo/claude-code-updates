"""既存の通知仕様を保ったまま radar-core の汎用処理を利用する。"""

from __future__ import annotations


def clip(value: str, limit: int) -> str:
    """正の上限は共有実装へ委譲し、0以下では従来の結果を維持する。"""
    if limit > 0:
        # 状態復元など、依存導入前に通知モジュールを読む処理も維持する。
        from radar_core.discord import clip as core_clip

        return core_clip(value, limit)
    if len(value.encode("utf-16-le")) // 2 <= limit:
        return value
    return (
        value.encode("utf-16-le")[: (limit - 1) * 2].decode("utf-16-le", "ignore") + "…"
    )
