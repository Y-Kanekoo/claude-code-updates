#!/usr/bin/env python3
"""
Claude Code リリースチェッカー

GitHub APIでanthropics/claude-codeのリリースを監視し、
新規リリースをGroq APIで要約して保存します。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from groq import Groq


# 定数
GITHUB_API_URL = "https://api.github.com/repos/anthropics/claude-code/releases"
REPORTS_DIR = Path(__file__).parent.parent / "reports" / "claude-code"
LAST_CHECKED_FILE = REPORTS_DIR / "last-checked.json"
LLM_MODEL = "llama-3.3-70b-versatile"
DISCORD_EMBED_COLOR = 0x8B5CF6  # 紫色
SECTION_LABELS = [
    ("TL;DR",              "📌 TL;DR"),
    ("破壊的変更",          "⚠️ 破壊的変更"),
    ("先に押さえるポイント", "⚡ 先に押さえるポイント"),
    ("新機能",              "✨ 新機能"),
    ("改善",                "🔧 改善"),
    ("バグ修正",            "🐛 バグ修正"),
]
GITHUB_REPO_URL = "https://github.com/anthropics/claude-code"
DOCS_BASE_URL = "https://docs.anthropic.com/ja/docs/claude-code"


class ReleaseChecker:
    """Claude Codeのリリースをチェックするクラス"""

    def __init__(self):
        """初期化処理"""
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        if not self.groq_api_key:
            raise ValueError("環境変数 GROQ_API_KEY が設定されていません")

        # Groq APIの設定
        self.client = Groq(api_key=self.groq_api_key)

        # GitHub APIトークン（任意）
        self.github_token = os.getenv("GITHUB_TOKEN")

        # Discord Webhook URL（任意）
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

        # reportsディレクトリが存在しない場合は作成
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def get_last_checked_version(self) -> Optional[str]:
        """前回チェックしたバージョンを取得"""
        if not LAST_CHECKED_FILE.exists():
            print("前回のチェック記録が見つかりません。初回実行として扱います。")
            return None

        try:
            with open(LAST_CHECKED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                version = data.get("last_version")
                print(f"前回チェック済みバージョン: {version}")
                return version
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: last-checked.json の読み込みに失敗しました: {e}")
            return None

    def save_last_checked_version(self, version: str, release_date: str):
        """チェックしたバージョンを保存"""
        data = {
            "last_version": version,
            "last_checked_date": datetime.now().isoformat(),
            "release_date": release_date
        }

        try:
            with open(LAST_CHECKED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"チェック記録を保存しました: {version}")
        except IOError as e:
            print(f"エラー: チェック記録の保存に失敗しました: {e}")
            raise

    def fetch_releases(self) -> List[Dict]:
        """GitHub APIからリリース一覧を取得"""
        print("GitHub APIからリリース情報を取得中...")

        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
            print("GitHub認証済みリクエストを使用します")

        try:
            response = requests.get(
                GITHUB_API_URL,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()

            releases = response.json()
            print(f"{len(releases)} 件のリリースを取得しました")
            return releases

        except requests.exceptions.RequestException as e:
            print(f"エラー: GitHub APIへのアクセスに失敗しました: {e}")
            raise
        except json.JSONDecodeError as e:
            print(f"エラー: レスポンスのJSONパースに失敗しました: {e}")
            raise

    def filter_new_releases(
        self,
        releases: List[Dict],
        last_version: Optional[str]
    ) -> List[Dict]:
        """新規リリースのみをフィルタリング"""
        if not last_version:
            # 初回実行時は最新1件のみ処理
            print("初回実行: 最新リリースのみを処理します")
            return releases[:1] if releases else []

        new_releases = []
        for release in releases:
            version = release.get("tag_name", "")
            if version == last_version:
                # 前回チェック済みバージョンに到達したら終了
                break
            new_releases.append(release)

        if new_releases:
            print(f"{len(new_releases)} 件の新規リリースが見つかりました")
        else:
            print("新規リリースは見つかりませんでした")

        return new_releases

    def summarize_release_notes(self, release_notes: str, version: str) -> str:
        """Groq APIでリリースノートを日本語要約"""
        print(f"リリースノート {version} を要約中...")

        prompt = f"""以下は `Claude Code` のリリースノートです。日本のエンジニア向けに、Markdown で読みやすく要約してください。

出力ルール:
- Markdown のみを出力し、前置き・説明・締めの一文は書かない
- 見出し名は以下の指定を一字一句そのまま使い、順番も固定する
- すべての見出しを必ず出す。省略・追加・改名をしない
- 各見出しの本文は「- 」で始まる箇条書き、または「なし」のどちらかにする
- 各セクション最大3項目まで。重要度の低い項目から削る
- 各箇条書きは1文で簡潔に書く
- 重要度順に整理する。最優先は破壊的変更と要対応事項
- 製品名、CLI コマンド、設定キー、API 名、コード識別子は原文のまま `backticks` で残す
- 不自然な直訳を避け、日本語として自然に言い換える
- 推測しない。原文にない効果・意図・背景は書かない
- 影響対象は原文から明確な場合のみ書く
- 同じ内容を複数セクションに重複して書かない
- 表・番号付きリスト・入れ子リスト・コードブロックは使わない
- 影響度の基準:
  - 高: 破壊的変更・移行必須・既定動作の変更が明確にある
  - 中: よく使う機能・CLI・CIへの実質的な変更がある
  - 低: 限定的な改善やバグ修正が中心
  - 要確認: 原文だけでは判断しきれない
- 破壊的変更: 互換性破壊・削除・移行必須が原文から明確なら「あり」、原文に明示がなければ「公式リリースノート上の明示なし」、不明なら「要確認」

必ず次の形式で出力すること:

### TL;DR
- （このリリースで最も重要な変更を1〜2文で要約）
- **影響度**: 高 / 中 / 低 / 要確認
- **破壊的変更**: あり / 公式リリースノート上の明示なし / 要確認

### 破壊的変更
（破壊的変更が原文に明記されていれば箇条書き、なければ「公式リリースノート上の明示なし」）

### 先に押さえるポイント
（意思決定に重要な情報を3項目以内で。「誰に影響するか」「何を確認すべきか」「注意点」を優先。なければ「なし」）

### 新機能
（新機能があれば箇条書き、なければ「なし」）

### 改善
（改善があれば箇条書き、なければ「なし」）

### バグ修正
（バグ修正があれば箇条書き、なければ「なし」）

リリースノート:
{release_notes}
"""

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}]
            )
            summary = response.choices[0].message.content.strip()
            print(f"要約完了: {version}")
            return summary

        except Exception as e:
            print(f"エラー: Groq APIでの要約に失敗しました: {e}")
            raise

    def create_report(
        self,
        release: Dict,
        summary: str,
        prev_version: Optional[str] = None,
    ) -> str:
        """レポートファイルを作成"""
        version = release.get("tag_name", "unknown")
        published_at = release.get("published_at", "")
        html_url = release.get("html_url", "")

        # 日付をパース
        try:
            release_date = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )
            date_str = release_date.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            date_str = datetime.now().strftime("%Y-%m-%d")

        # 関連リンクを構築
        related_links = [
            f"- [GitHub Release]({html_url})",
        ]
        if prev_version:
            compare_url = f"{GITHUB_REPO_URL}/compare/{prev_version}...{version}"
            related_links.append(f"- [差分比較: {prev_version}...{version}]({compare_url})")
        related_links += [
            f"- [Claude Code 公式ドキュメント]({DOCS_BASE_URL})",
            f"- [変更履歴]({DOCS_BASE_URL}/changelog)",
        ]
        related_links_md = "\n".join(related_links)

        # レポート内容を生成
        report_content = f"""# Claude Code 更新レポート

## {version}

- **リリース日**: {date_str}
- **リリースページ**: [GitHub →]({html_url})

{summary}

### 関連リンク

{related_links_md}

---
*このレポートは自動生成されています*
"""

        # ファイル名を生成: YYYY-MM-DD-vX.X.X.md
        filename = f"{date_str}-{version}.md"
        report_path = REPORTS_DIR / filename

        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_content)
            print(f"レポートを保存しました: {report_path}")
            return date_str

        except IOError as e:
            print(f"エラー: レポートファイルの保存に失敗しました: {e}")
            raise

    def _parse_sections(self, summary: str) -> Dict[str, str]:
        """summaryを ### セクション名 ごとに分割して辞書で返す"""
        sections: Dict[str, str] = {}
        current_key = None
        current_lines: List[str] = []

        for line in summary.splitlines():
            if line.startswith("### "):
                if current_key:
                    sections[current_key] = "\n".join(current_lines).strip()
                current_key = line[4:].strip()
                current_lines = []
            elif current_key:
                current_lines.append(line)

        if current_key:
            sections[current_key] = "\n".join(current_lines).strip()

        return sections

    def _extract_tldr(self, summary: str) -> str:
        """summaryのTL;DRセクションから要約文（最初の非メタ箇条書き）を抽出"""
        sections = self._parse_sections(summary)
        tldr_text = sections.get("TL;DR", "")
        for line in tldr_text.splitlines():
            stripped = line.lstrip("- ").strip()
            # **影響度**: や **破壊的変更**: などのメタ行を除外
            if stripped and not stripped.startswith("**"):
                return stripped
        return summary[:200]  # フォールバック

    def send_discord_notification(self, release: Dict, summary: str):
        """Discord Webhookに新リリース通知を送信"""
        if not self.discord_webhook_url:
            print("Discord Webhook URLが設定されていないため、通知をスキップします")
            return

        version = release.get("tag_name", "unknown")
        published_at = release.get("published_at", "")
        html_url = release.get("html_url", "")

        # TL;DRをdescriptionに、各セクションをfieldsに設定
        description = self._extract_tldr(summary)
        sections = self._parse_sections(summary)

        fields = []
        for key, label in SECTION_LABELS:
            value = sections.get(key, "なし")
            if not value.strip():
                value = "なし"
            # Discord field valueは1024文字上限
            if len(value) > 1024:
                value = value[:1020] + "\n..."
            fields.append({"name": label, "value": value, "inline": True})

        payload = {
            "embeds": [{
                "title": f"Claude Code {version} がリリースされました",
                "description": description,
                "color": DISCORD_EMBED_COLOR,
                "url": html_url,
                "fields": fields,
                "footer": {"text": "Claude Code Updates"},
                "timestamp": published_at
            }]
        }

        try:
            response = requests.post(
                self.discord_webhook_url,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            print(f"Discord通知を送信しました: {version}")
        except requests.exceptions.RequestException as e:
            # 通知失敗は致命的エラーとしない
            print(f"警告: Discord通知の送信に失敗しました: {e}")

    def run(self):
        """メイン処理"""
        print("=" * 60)
        print("Claude Code リリースチェッカー")
        print("=" * 60)

        try:
            # 前回チェックしたバージョンを取得
            last_version = self.get_last_checked_version()

            # リリース一覧を取得
            releases = self.fetch_releases()

            if not releases:
                print("リリースが見つかりませんでした")
                return

            # 新規リリースをフィルタリング
            new_releases = self.filter_new_releases(releases, last_version)

            if not new_releases:
                print("処理を終了します")
                return

            # 各リリースを処理（古い順に処理）
            new_releases.reverse()
            latest_version = None
            latest_date = None
            prev_version = last_version  # compare URL用に前バージョンを追跡

            for release in new_releases:
                version = release.get("tag_name", "unknown")
                release_notes = release.get("body", "リリースノートがありません")

                print("-" * 60)
                print(f"処理中: {version}")

                # リリースノートを要約
                summary = self.summarize_release_notes(release_notes, version)

                # レポートを作成
                date_str = self.create_report(release, summary, prev_version)

                # Discord通知を送信
                self.send_discord_notification(release, summary)

                latest_version = version
                latest_date = date_str
                prev_version = version  # 次のリリースのprev_versionとして使用

            # 最新バージョンを保存
            if latest_version:
                self.save_last_checked_version(latest_version, latest_date)

            print("=" * 60)
            print(f"処理完了: {len(new_releases)} 件のレポートを作成しました")
            print("=" * 60)

        except Exception as e:
            print(f"エラーが発生しました: {e}")
            sys.exit(1)


def main():
    """エントリーポイント"""
    try:
        checker = ReleaseChecker()
        checker.run()
    except KeyboardInterrupt:
        print("\n処理を中断しました")
        sys.exit(1)
    except Exception as e:
        print(f"致命的なエラー: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
