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
from typing import Dict, List, Mapping, Optional

import requests

try:
    from groq import Groq
except ModuleNotFoundError:
    Groq = None

try:
    from report_schema import (
        build_header_table,
        extract_judgement,
        extract_summary,
        is_empty_release,
        parse_sections,
        pick_discord_color,
        validate_report,
    )
except ModuleNotFoundError:
    from scripts.report_schema import (
        build_header_table,
        extract_judgement,
        extract_summary,
        is_empty_release,
        parse_sections,
        pick_discord_color,
        validate_report,
    )


# 定数
GITHUB_API_URL = "https://api.github.com/repos/anthropics/claude-code/releases"
REPORTS_DIR = Path(__file__).parent.parent / "reports" / "claude-code"
LAST_CHECKED_FILE = REPORTS_DIR / "last-checked.json"
LLM_MODEL = "llama-3.3-70b-versatile"
SECTION_FIELDS = [
    ("judgement", "📊 判定", True, False),
    ("links", "🔗 リンク", True, False),
    ("breaking_changes", "⚠️ 破壊的変更", False, False),
    ("highlights", "⚡ 先に押さえる", False, True),
    ("changes", "📝 変更内容", False, True),
    ("impact", "🎯 影響範囲", False, True),
    ("recommended_action", "✅ 推奨対応", False, True),
    ("notes", "📌 補足", False, True),
    ("media", "🎬 資料", False, True),
]
GITHUB_REPO_URL = "https://github.com/anthropics/claude-code"
DOCS_BASE_URL = "https://docs.anthropic.com/ja/docs/claude-code"
SLIDES_BASE_URL = "https://y-kanekoo.github.io/claude-code-updates/slides"
MEDIA_INDEX_FILE = REPORTS_DIR / ".media-index.json"
EMPTY_RELEASE_BANNER = (
    "> ℹ️ このリリースは公開情報の変更が原文に記載されていません。"
    "内部リリースの可能性があります。"
)


class ReleaseChecker:
    """Claude Codeのリリースをチェックするクラス"""

    def __init__(self):
        """初期化処理"""
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        if not self.groq_api_key:
            raise ValueError("環境変数 GROQ_API_KEY が設定されていません")
        if Groq is None:
            raise ImportError("groq パッケージがインストールされていません")

        # Groq APIの設定
        self.client = Groq(api_key=self.groq_api_key)

        # GitHub APIトークン（任意）
        self.github_token = os.getenv("GITHUB_TOKEN")

        # Discord Webhook URL（任意）
        self.discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

        # Discord通知で保存済みレポート本文を再利用する
        self.report_content_by_version: Dict[str, str] = {}

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

        catalog_block = self._load_project_catalog()
        if catalog_block:
            catalog_section = f"\n{catalog_block}\n"
        else:
            catalog_section = ""

        prompt = f"""あなたの役割は、`Claude Code` のリリースノートから固定スキーマを埋めることです。読みやすく要約することは従属目標です。

出力全体のルール:
- Markdown断片のみを出力し、前置き・説明・締めの一文は書かない
- 許可する見出し以外を追加しない
- 見出し名・順番・HTMLコメントを一字一句そのまま使う
- 各見出し直上のHTMLコメントは必ず出力し、改変・省略しない
- `### 関連リンク` は出力しない
- 変更内容セクションを除き、各セクション本文は「- 」で始まる箇条書き、または「なし」のどちらかにする
- 表・番号付きリスト・コードブロックは禁止。入れ子リストは変更内容セクションのみ1階層まで許可
- 各セクション最大3項目まで（変更内容はサブ見出し当たり3項目まで、最大4サブ見出しまで可）。重要度の低い項目から削る
- 変更内容セクションの詳細行を除き、各箇条書きは1文で簡潔に書く
- 推測しない。原文にない効果・意図・背景は書かない
- 製品名、CLI コマンド、設定キー、API 名、コード識別子は原文の表記を保持し、必要に応じて `backticks` で残す
- 不自然な直訳を避け、日本語として自然に言い換える
- 影響対象は原文から明確な場合のみ書く
- 同じ内容を複数セクションに重複して書かない

許可する見出しと対応HTMLコメント:
1. <!-- section:summary --> の直下に ### 要約
2. <!-- section:judgement --> の直下に ### 判定
3. <!-- section:highlights --> の直下に ### 先に押さえるポイント
4. <!-- section:changes --> の直下に ### 変更内容
5. <!-- section:breaking_changes --> の直下に ### 破壊的変更
6. <!-- section:impact --> の直下に ### 影響範囲
7. <!-- section:recommended_action --> の直下に ### 推奨対応
8. <!-- section:notes --> の直下に ### 補足

要約セクション:
- 1文のみ出力する
- メタ情報は書かない。影響度・破壊的変更・推奨アクションは判定セクションに分離する

判定セクション:
- 次の4行だけを固定順で出力する
- 半角コロンを必ず使う。全角「：」は禁止
- 強調範囲は必ず `**キー名**:` の形にする。`**キー名:**` や `**キー名**：`は禁止
- **影響度**: 高 | 中 | 低 | 要確認
- **破壊的変更**: あり | 公式リリースノート上の明示なし | 要確認
- **変更記載**: あり | 具体的な変更記載なし
- **推奨アクション**: 即対応 | 次回更新時に確認 | 様子見

変更内容セクション:
- 以下のサブ見出しを使って分類して良い（使わず従来の箇条書き1階層でも可）
  - #### 新機能
  - #### 改善
  - #### バグ修正
  - #### 廃止予定
  - #### セキュリティ
- 該当がないサブ見出しは出力しない
- 各サブ見出し配下は「- 」で始まる箇条書きのみ。番号付きリストは禁止
- 各項目は次の形式が望ましい:
  - **項目の要旨**
    - 関連: `コマンド名` / `ファイル名` / `オプション名`
    - 追加の1文（必要な場合のみ）
- 入れ子は1階層まで。孫リスト（入れ子のさらに入れ子）は禁止
- 原文にサブ見出しの分類根拠がない場合は、分類せず従来の「- 箇条書き」のみにする
- 全体が「なし」の場合はサブ見出しを出さず `なし` の1語のみ
- コマンド名・設定キー・オプション名は必ず `backticks` で囲む

判定基準:
- 影響度 高: 破壊的変更・移行必須・既定動作の変更が明確にある
- 影響度 中: よく使う機能・CLI・CIへの実質的な変更がある
- 影響度 低: 限定的な改善やバグ修正が中心
- 影響度 要確認: 原文だけでは判断しきれない
- 破壊的変更: 互換性破壊・削除・移行必須が原文から明確なら「あり」、原文に明示がなければ「公式リリースノート上の明示なし」、不明なら「要確認」

空リリースの扱い:
- 原文に具体的な変更記載がない場合だけ空リリースとする
- 要約は「公式リリースノートに具体的な変更記載はありません。」で固定する
- 判定は「影響度=要確認」「破壊的変更=要確認」「変更記載=具体的な変更記載なし」「推奨アクション=様子見」で固定する
- 先に押さえるポイント、変更内容、破壊的変更、影響範囲、推奨対応、補足はすべて「なし」にする

Few-shot例:
<!-- section:summary -->
### 要約
- `/team-onboarding` コマンド追加と OS CA 証明書ストアの既定有効化が目玉です。

<!-- section:judgement -->
### 判定
- **影響度**: 中
- **破壊的変更**: 公式リリースノート上の明示なし
- **変更記載**: あり
- **推奨アクション**: 次回更新時に確認

<!-- section:highlights -->
### 先に押さえるポイント
- 企業環境では OS CA の既定有効化で社内 CA カスタム設定が不要になる場合があります。
- `/team-onboarding` はチーム運用の標準化に活用できます。

<!-- section:changes -->
### 変更内容

#### 新機能
- **`/team-onboarding` コマンド追加**
  - 関連: `/team-onboarding`
  - チーム導入向けの対話式ウィザード。

#### 改善
- **OS CA 証明書ストアの既定有効化**
  - 関連: `settings.json`
  - 以前は opt-in、このバージョンで opt-out に変更。

#### バグ修正
- **Bedrock 認証エラーの修正**
  - 関連: `AWS_BEARER_TOKEN_BEDROCK`
  - 403 `Authorization header is missing` で失敗する問題を解消。

<!-- section:breaking_changes -->
### 破壊的変更
なし

<!-- section:impact -->
### 影響範囲
- Claude Code を CLI から運用しているチームに影響します。
- 社内 CA を独自設定していた環境は挙動が変わる可能性があります。

<!-- section:recommended_action -->
### 推奨対応
- 次回更新時に CA 設定と `/team-onboarding` の導入可否を確認してください。

<!-- section:notes -->
### 補足
なし

出力形式:
<!-- section:summary -->
### 要約
- （1文のみ）

<!-- section:judgement -->
### 判定
- **影響度**: 高 | 中 | 低 | 要確認
- **破壊的変更**: あり | 公式リリースノート上の明示なし | 要確認
- **変更記載**: あり | 具体的な変更記載なし
- **推奨アクション**: 即対応 | 次回更新時に確認 | 様子見

<!-- section:highlights -->
### 先に押さえるポイント
（箇条書き、または「なし」）

<!-- section:changes -->
### 変更内容
（サブ見出し付き箇条書き、従来形式の箇条書き、または「なし」）

<!-- section:breaking_changes -->
### 破壊的変更
（箇条書き、または「なし」）

<!-- section:impact -->
### 影響範囲
（箇条書き、または「なし」）

<!-- section:recommended_action -->
### 推奨対応
（箇条書き、または「なし」）

<!-- section:notes -->
### 補足
（箇条書き、または「なし」）
{catalog_section}

リリースノート:
{release_notes}
"""

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            summary = response.choices[0].message.content.strip()
            print(f"要約完了: {version}")
            return summary

        except Exception as e:
            print(f"エラー: Groq APIでの要約に失敗しました: {e}")
            raise

    def _load_project_catalog(self) -> str:
        """プロジェクトカタログを読み込みプロンプト用の短い参考情報文字列に変換する。"""
        catalog_path = REPORTS_DIR / ".project_catalog.json"
        if not catalog_path.exists():
            return ""

        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return ""

        projects = data.get("projects", [])
        if not projects:
            return ""

        # 直近60日フィルタ + 上位15件
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=60)).isoformat()
        filtered = [
            p for p in projects
            if p.get("last_active") and p["last_active"] >= cutoff
        ][:15]

        if not filtered:
            return ""

        lines = ["参考情報: ユーザーの主要プロジェクト（直近60日アクティブ、最大15件）"]
        for p in filtered:
            stack = "/".join(p.get("stack", [])[:3]) or "—"
            intent = p.get("intent", "") or "—"
            lines.append(f"- {p['name']} ({stack}, {intent}, {p['last_active']})")
        lines.append("")
        lines.append("Claude Code の変更がこれらプロジェクトに関連する場合、")
        lines.append("「影響範囲」セクションで具体的なプロジェクト名に触れてください。")
        lines.append("それ以外は触れないでください。")

        return "\n".join(lines)

    def create_report(
        self,
        release: Mapping[str, object],
        summary: str,
        prev_version: Optional[str] = None,
    ) -> str:
        """レポートファイルを作成"""
        version = str(release.get("tag_name", "unknown"))
        published_at = str(release.get("published_at", ""))

        # 日付をパース
        try:
            release_date = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )
            date_str = release_date.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            date_str = datetime.now().strftime("%Y-%m-%d")

        sections = parse_sections(summary)
        judgement = extract_judgement(sections)
        header_table = build_header_table(judgement, date_str)
        related_links_md = self._build_related_links(release, prev_version)

        # レポート内容を生成
        if is_empty_release(judgement):
            summary_body = self._build_empty_release_summary()
            footer = "<sub>自動生成 / リリースノート記載なし</sub>"
            report_content = f"""# Claude Code 更新レポート / {version}

{header_table}
<!-- section:links -->
### 関連リンク
{related_links_md}

{EMPTY_RELEASE_BANNER}

{summary_body}

---
{footer}
"""
        else:
            footer = f"<sub>自動生成 / Groq {LLM_MODEL} 要約</sub>"
            report_content = f"""# Claude Code 更新レポート / {version}

{header_table}
<!-- section:links -->
### 関連リンク
{related_links_md}

{summary.strip()}

---
{footer}
"""

        errors = validate_report(report_content)
        if errors:
            joined_errors = "\n".join(f"- {error}" for error in errors)
            raise ValueError(f"レポート保存前検証に失敗しました。\n{joined_errors}")

        # ファイル名を生成: YYYY-MM-DD-vX.X.X.md
        filename = f"{date_str}-{version}.md"
        report_path = REPORTS_DIR / filename

        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_content)
            self.report_content_by_version[str(version)] = report_content
            print(f"レポートを保存しました: {report_path}")
            return date_str

        except IOError as e:
            print(f"エラー: レポートファイルの保存に失敗しました: {e}")
            raise

    def _build_related_links(
        self,
        release: Mapping[str, object],
        prev_version: Optional[str] = None,
    ) -> str:
        """レポートとDiscord通知で使う関連リンクMarkdownを組み立てる。"""
        version = str(release.get("tag_name", "unknown"))
        html_url = str(release.get("html_url", ""))
        related_links = [
            f"- [GitHub Release]({html_url})",
        ]

        if prev_version:
            compare_url = f"{GITHUB_REPO_URL}/compare/{prev_version}...{version}"
            related_links.append(f"- [差分 {prev_version}...{version}]({compare_url})")

        related_links += [
            f"- [公式ドキュメント]({DOCS_BASE_URL})",
            f"- [変更履歴]({DOCS_BASE_URL}/changelog)",
        ]
        return "\n".join(related_links)

    def _build_media_value(self, release: Mapping[str, object], date_str: str) -> str:
        """Discord media field の値を組み立てる。スライドURLと任意の音声URLを返す。"""
        version = str(release.get("tag_name", "unknown"))
        slide_filename = f"{date_str}-{version}.html"
        slide_url = f"{SLIDES_BASE_URL}/{slide_filename}"

        lines = [f"📊 スライド: {slide_url}"]

        audio_url = self._lookup_audio_url(version)
        if audio_url:
            lines.append(f"🎙️ 音声解説: {audio_url}")

        return "\n".join(lines)

    def _lookup_audio_url(self, version: str) -> str:
        """.media-index.json から指定バージョンの音声URLを取得する。"""
        if not MEDIA_INDEX_FILE.exists():
            return ""

        try:
            with open(MEDIA_INDEX_FILE, "r", encoding="utf-8") as f:
                data: object = json.load(f)
        except (json.JSONDecodeError, IOError):
            return ""

        if not isinstance(data, dict):
            return ""

        entry = data.get(version, {})
        if not isinstance(entry, dict):
            return ""

        audio_url = entry.get("audio_url", "")
        if not isinstance(audio_url, str):
            return ""
        return audio_url

    def _extract_date_from_release(self, release: Mapping[str, object]) -> str:
        """release dict から YYYY-MM-DD の日付文字列を取り出す。"""
        published_at = str(release.get("published_at", ""))
        try:
            release_date = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )
            return release_date.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            return datetime.now().strftime("%Y-%m-%d")

    def _build_empty_release_summary(self) -> str:
        """空リリース用の最小summary断片を返す。"""
        return """<!-- section:summary -->
### 要約
- 公式リリースノートに具体的な変更記載はありません。

<!-- section:judgement -->
### 判定
- **影響度**: 要確認
- **破壊的変更**: 要確認
- **変更記載**: 具体的な変更記載なし
- **推奨アクション**: 様子見"""

    def send_discord_notification(self, release: Mapping[str, object], summary: str):
        """Discord Webhookに新リリース通知を送信"""
        if not self.discord_webhook_url:
            print("Discord Webhook URLが設定されていないため、通知をスキップします")
            return

        version = str(release.get("tag_name", "unknown"))
        published_at = str(release.get("published_at", ""))
        html_url = str(release.get("html_url", ""))

        source_markdown = self._build_notification_source(release, summary)
        sections = parse_sections(source_markdown)
        judgement = extract_judgement(sections)

        if is_empty_release(judgement):
            description = "公式リリースノートに具体的な変更記載はありません。"
            date_str = self._extract_date_from_release(release)
            media_value = self._build_media_value(release, date_str)
            fields: List[Dict[str, object]] = [
                {
                    "name": "📄 リリースノート",
                    "value": "具体的な変更記載なし。詳細は原文を参照してください。",
                    "inline": False,
                },
                {
                    "name": "🎬 資料",
                    "value": media_value,
                    "inline": False,
                },
            ]
        else:
            description = extract_summary(sections)
            # media は LLM が生成しないためここで注入
            date_str = self._extract_date_from_release(release)
            sections["media"] = self._build_media_value(release, date_str)

            fields = []
            for internal_id, label, inline, omit_if_none in SECTION_FIELDS:
                value = sections.get(internal_id, "").strip()
                if not value:
                    value = "なし"
                if omit_if_none and value == "なし":
                    continue
                fields.append({
                    "name": label,
                    "value": self._truncate_discord_field(value),
                    "inline": inline,
                })

        payload: Dict[str, object] = {
            "embeds": [{
                "title": f"Claude Code {version} がリリースされました",
                "description": description,
                "color": pick_discord_color(judgement),
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

    def _build_notification_source(self, release: Mapping[str, object], summary: str) -> str:
        """Discord通知用に解析対象Markdownを用意する。"""
        version = str(release.get("tag_name", "unknown"))
        report_content = self.report_content_by_version.get(version)
        if report_content:
            return report_content

        related_links_md = self._build_related_links(release)
        return f"""{summary.strip()}

<!-- section:links -->
### 関連リンク
{related_links_md}
"""

    def _truncate_discord_field(self, value: str) -> str:
        """Discord fieldの1024文字制限に合わせて箇条書き単位で詰める。"""
        limit = 1024
        if len(value) <= limit:
            return value

        suffix = "\n→ 詳細はレポート本文へ"
        available = limit - len(suffix)
        selected_lines: List[str] = []
        current = ""

        for line in value.splitlines():
            candidate = line if not current else f"{current}\n{line}"
            if len(candidate) > available:
                break
            selected_lines.append(line)
            current = candidate

        if selected_lines:
            return f"{current}{suffix}"
        return suffix.lstrip()

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
