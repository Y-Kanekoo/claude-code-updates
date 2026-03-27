#!/usr/bin/env python3
"""
Claude Code リリースチェッカー

GitHub APIでanthropics/claude-codeのリリースを監視し、
新規リリースをGemini APIで要約して保存します。
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from google import genai


# 定数
GITHUB_API_URL = "https://api.github.com/repos/anthropics/claude-code/releases"
REPORTS_DIR = Path(__file__).parent.parent / "reports" / "claude-code"
LAST_CHECKED_FILE = REPORTS_DIR / "last-checked.json"
GEMINI_MODEL = "gemini-2.5-flash"


class ReleaseChecker:
    """Claude Codeのリリースをチェックするクラス"""

    def __init__(self):
        """初期化処理"""
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not self.gemini_api_key:
            raise ValueError("環境変数 GEMINI_API_KEY が設定されていません")

        # Gemini APIクライアントの設定
        self.client = genai.Client(api_key=self.gemini_api_key)

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

        try:
            response = requests.get(
                GITHUB_API_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
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
        """Gemini APIでリリースノートを日本語要約"""
        print(f"リリースノート {version} を要約中...")

        prompt = f"""以下のClaude Codeのリリースノートを日本語で要約してください。

リリースノート:
{release_notes}

要約は以下の形式で出力してください:

### 新機能
（新機能があれば箇条書きで記載、なければ「なし」）

### 改善
（改善があれば箇条書きで記載、なければ「なし」）

### バグ修正
（バグ修正があれば箇条書きで記載、なければ「なし」）

### 破壊的変更
（破壊的変更があれば箇条書きで記載、なければ「なし」）

注意事項:
- 各項目は簡潔な日本語で記載してください
- 技術的な詳細は適度に含めてください
- 箇条書きは「-」で始めてください
- セクションの見出し（###）は必ず含めてください
"""

        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            summary = response.text.strip()
            print(f"要約完了: {version}")
            return summary

        except Exception as e:
            print(f"エラー: Gemini APIでの要約に失敗しました: {e}")
            raise

    def create_report(
        self,
        release: Dict,
        summary: str
    ) -> str:
        """レポートファイルを作成"""
        version = release.get("tag_name", "unknown")
        published_at = release.get("published_at", "")

        # 日付をパース
        try:
            release_date = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )
            date_str = release_date.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            date_str = datetime.now().strftime("%Y-%m-%d")

        # レポート内容を生成
        report_content = f"""# Claude Code 更新レポート

## {version} ({date_str})

{summary}

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

            for release in new_releases:
                version = release.get("tag_name", "unknown")
                release_notes = release.get("body", "リリースノートがありません")

                print("-" * 60)
                print(f"処理中: {version}")

                # リリースノートを要約
                summary = self.summarize_release_notes(release_notes, version)

                # レポートを作成
                date_str = self.create_report(release, summary)

                latest_version = version
                latest_date = date_str

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
