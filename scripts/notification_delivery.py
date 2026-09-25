"""公開済みレポートと運用障害を、永続化した送信状態から通知する。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error, request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, quote

try:
    from report_schema import (
        extract_judgement,
        extract_summary,
        parse_sections,
        pick_discord_color,
    )
except ImportError:
    from scripts.report_schema import (
        extract_judgement,
        extract_summary,
        parse_sections,
        pick_discord_color,
    )

STATE_NAME = "notification-state.json"
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports" / "claude-code"
INCIDENTS = {
    "groq_rate_limit": (
        "Groq APIの利用上限に到達しました",
        "要約APIの利用枠が回復するまで、新しいレポートの生成を保留しています。",
        "次回の日次実行で再試行します。継続する場合はGroqの利用上限を確認してください。",
    ),
    "groq_input_too_large": (
        "要約APIの入力サイズ上限を超えました",
        "リリースノートを分割してもAPIの上限に収まりませんでした。",
        "入力分割の設定を確認してください。同じ入力の再送やAPIキー再発行では解消しません。",
    ),
    "groq_authentication": (
        "Groq APIの認証を確認してください",
        "APIキーが無効・期限切れ、または必要な権限がありません。",
        "GitHub SecretsのCLAUDE_UPDATES_GROQ_API_KEYとGroq側の権限を確認してください。",
    ),
    "groq_model": (
        "要約モデルを利用できません",
        "指定モデルが利用できないか、モデルへのアクセスが許可されていません。",
        "CLAUDE_UPDATES_GROQ_MODELとGroqのModel Permissionsを確認してください。",
    ),
    "workflow_failure": (
        "更新処理を完了できませんでした",
        "取得・生成・検証・公開のいずれかの工程で停止しました。",
        "Actionsログの失敗した工程を確認してください。未完了分は次回実行の対象になります。",
    ),
}


def atomic_json(path: Path, value: object) -> None:
    """送信状態を同じディレクトリ内で置換する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def clip(value: str, limit: int) -> str:
    """絵文字を含め、DiscordのUTF-16文字数制限以内に収める。"""
    if len(value.encode("utf-16-le")) // 2 <= limit:
        return value
    return (
        value.encode("utf-16-le")[: (limit - 1) * 2].decode(
            "utf-16-le", errors="ignore"
        )
        + "…"
    )


def excerpt(body: str, count: int = 3, limit: int = 600) -> str:
    """根拠コメントや小見出しを通知から除き、要点だけを取り出す。"""
    lines = [line for line in body.splitlines() if line.startswith("- ")]
    return clip("\n".join(lines[:count]), limit)


def build_release_payload(
    release: Mapping[str, object], markdown: str
) -> dict[str, object]:
    """判断と対応を先に示す短い通知を組み立てる。"""
    version = str(release["tag_name"])
    date_str = str(release["published_at"])[:10]
    repository = os.getenv("GITHUB_REPOSITORY", "Y-Kanekoo/claude-code-updates")
    branch = quote(os.getenv("GITHUB_REF_NAME", "main"), safe="")
    report_url = f"https://github.com/{repository}/blob/{branch}/reports/claude-code/{date_str}-{version}.md"
    sections = parse_sections(markdown)
    judgement = extract_judgement(sections)
    action = judgement.get("推奨アクション", "次回更新時に確認")
    fields: list[dict[str, object]] = []
    for section, label in (
        ("recommended_action", "必要な対応"),
        ("impact", "対象の使い方"),
        ("highlights", "主な変更"),
    ):
        value = excerpt(sections.get(section, ""))
        if value:
            fields.append({"name": label, "value": value, "inline": False})
    if judgement.get("破壊的変更") == "あり":
        fields.insert(
            0,
            {
                "name": "互換性の変更あり",
                "value": excerpt(sections.get("breaking_changes", ""))
                or "更新前にレポートの破壊的変更を確認してください。",
                "inline": False,
            },
        )
    fields.append(
        {
            "name": "詳細と原文",
            "value": (
                f"[日本語レポート]({report_url}) · [公式リリース]({release['html_url']})"
            ),
            "inline": False,
        }
    )
    description = extract_summary(sections) or "更新内容をレポートにまとめました。"
    if "<!-- generation:source-fallback -->" in markdown:
        description = (
            "一部または全部の日本語要約を生成できず、原文を掲載しています。\n"
            + description
        )
    return {
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": clip(f"Claude Code {version}｜{action}", 256),
                "description": clip(description, 800),
                "url": report_url,
                "color": pick_discord_color(judgement),
                "fields": fields,
                "footer": {
                    "text": "自動要約・判定です。詳細は公式リリースで確認できます。"
                },
                "timestamp": str(release["published_at"]),
            }
        ],
    }


class NotificationStore:
    """レポート生成済みと通知送信済みを別々に管理する。"""

    def __init__(self, path: Path):
        self.path = path
        self.data = {
            "schema_version": 1,
            "pending": {},
            "delivered": {},
            "incident": None,
        }
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(data, dict)
                    or data.get("schema_version") != 1
                    or not isinstance(data.get("pending"), dict)
                    or not isinstance(data.get("delivered"), dict)
                    or (
                        data.get("incident") is not None
                        and not isinstance(data["incident"], dict)
                    )
                ):
                    raise ValueError("通知状態の形式が不正です")
                for entry in data["pending"].values():
                    if not isinstance(entry, dict) or not isinstance(
                        entry.get("payload"), dict
                    ):
                        raise ValueError("未送信通知の形式が不正です")
                incident = data.get("incident")
                if incident is not None:
                    if not isinstance(incident.get("key"), str) or not isinstance(
                        incident.get("sent_at"), str
                    ):
                        raise ValueError("障害の通知状態が不正です")
                    if datetime.fromisoformat(incident["sent_at"]).tzinfo is None:
                        raise ValueError("障害通知の日付にタイムゾーンがありません")
                self.data = data
            except (ValueError, OSError) as exc:
                raise RuntimeError(
                    "通知状態を読み込めません。重複や欠落を防ぐため復旧してください。"
                ) from exc

    def save(self) -> None:
        atomic_json(self.path, self.data)

    def enqueue(
        self,
        version: str,
        payload: Mapping[str, object],
        *,
        requires_publication: bool = True,
    ) -> None:
        if version in self.data["delivered"]:
            return
        self.data["pending"][version] = {
            "payload": dict(payload),
            "requires_publication": requires_publication,
        }
        self.save()

    def deliver(
        self,
        send: Callable[[Mapping[str, object]], str],
        *,
        published: bool,
        failure_type: str = "",
        failed_version: str = "",
        run_url: str = "",
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(timezone.utc)
        for version, entry in list(self.data["pending"].items()):
            if published or entry.get("requires_publication", True) is False:
                message_id = send(entry["payload"])
                self.data["delivered"][version] = {
                    "message_id": message_id,
                    "sent_at": now.isoformat(),
                }
                del self.data["pending"][version]
                self.save()
                print(f"Discord通知を送信しました: {version}")
        incident = self.data["incident"]
        if failure_type:
            kind = failure_type if failure_type in INCIDENTS else "workflow_failure"
            key = f"{kind}:{failed_version}"
            if incident and incident.get("key") == key:
                last_sent = datetime.fromisoformat(incident["sent_at"])
                if now - last_sent < timedelta(days=7):
                    print("同じ障害の通知済みです。7日後までは再通知を抑制します。")
                    return
            title, reason, action = INCIDENTS[kind]
            lines = [f"⚠️ **{title}**", reason]
            if failed_version:
                lines.append(f"対象: Claude Code {failed_version}")
            lines += [
                f"**次の対応**: {action}",
                f"未送信の更新通知: {len(self.data['pending'])}件",
            ]
            if published:
                lines.append(
                    "公開済みの途中進捗は保持され、次回実行で続きから再開します。"
                )
            else:
                lines.append(
                    "今回のレポート公開は未確認です。更新通知は保留しています。"
                )
            if kind == "groq_rate_limit":
                lines.append(
                    "[現在の利用上限を確認](https://console.groq.com/settings/limits)"
                )
            if run_url:
                lines.append(f"[Actionsログを確認]({run_url})")
            send(
                {
                    "content": clip("\n".join(lines), 1900),
                    "allowed_mentions": {"parse": []},
                }
            )
            self.data["incident"] = {"key": key, "sent_at": now.isoformat()}
            self.save()
        elif published and incident:
            send(
                {
                    "content": "✅ Claude Code 更新処理が復旧しました。公開済みレポートの未送信通知も送信しました。"
                    + (f" [実行結果]({run_url})" if run_url else ""),
                    "allowed_mentions": {"parse": []},
                }
            )
            self.data["incident"] = None
            self.save()


def post_webhook(webhook_url: str, payload: Mapping[str, object]) -> str:
    """wait=trueで保存確認を受け、成功した通知だけを送信済みにする。"""
    parsed = urlsplit(webhook_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"discord.com", "discordapp.com"}
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d+/[^/]+", parsed.path)
    ):
        raise ValueError(
            "DISCORD_WEBHOOK_URLに有効なDiscord Webhook URLを設定してください。"
        )
    params = dict(parse_qsl(parsed.query))
    params["wait"] = "true"
    url = urlunsplit(parsed._replace(query=urlencode(params)))
    for attempt in range(3):
        try:
            req = request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Claude-Code-Updates",
                },
                method="POST",
            )
            with request.urlopen(req, timeout=30) as response:
                result = json.load(response)
                if not isinstance(result, dict) or not isinstance(
                    result.get("id"), str
                ):
                    raise RuntimeError(
                        "Discordからメッセージ保存の確認が得られませんでした。"
                    )
                return result["id"]
        except error.HTTPError as exc:
            if exc.code != 429 and not 500 <= exc.code <= 599:
                raise RuntimeError(
                    f"Discord通知に失敗しました（HTTP {exc.code}）。"
                ) from None
            delay = 2**attempt
            if exc.code == 429:
                try:
                    body = json.loads(exc.read())
                    delay = float(
                        body.get("retry_after", exc.headers.get("Retry-After", delay))
                    )
                except (ValueError, TypeError, AttributeError):
                    pass
            if not 0 <= delay <= 30 or attempt == 2:
                raise RuntimeError(
                    "Discordの一時障害が継続しています。通知を次回へ持ち越します。"
                ) from None
            time.sleep(delay)
        except (error.URLError, TimeoutError):
            if attempt == 2:
                raise RuntimeError(
                    "Discordに接続できません。通知を次回へ持ち越します。"
                ) from None
            time.sleep(2**attempt)
    raise RuntimeError("Discord通知を完了できませんでした。")


def main() -> int:
    """生成環境から独立して、公開後に未送信分と障害を通知する。"""
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print(
            "Discord Webhook未設定のため送信を保留します。未送信分は保存されています。"
        )
        return 0
    try:
        store = NotificationStore(REPORTS_DIR / STATE_NAME)
        store.deliver(
            lambda payload: post_webhook(webhook_url, payload),
            published=os.getenv("REPORTS_PUBLISHED") == "true",
            failure_type=os.getenv("FAILURE_TYPE", "")
            if os.getenv("RUN_FAILED") != "true"
            else os.getenv("FAILURE_TYPE", "") or "workflow_failure",
            failed_version=os.getenv("FAILED_VERSION", ""),
            run_url=os.getenv("ACTIONS_RUN_URL", ""),
        )
    except (RuntimeError, ValueError, OSError) as exc:
        reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(
            f"通知処理を完了できませんでした: {reason}。未送信分は再実行時に送信します。"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
