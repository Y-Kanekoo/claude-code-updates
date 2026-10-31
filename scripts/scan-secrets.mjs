// 秘密情報スキャン（テスト標準の static 段階）。依存パッケージなし。
// Git の追跡対象と未追跡（.gitignore 対象外）のテキストから既知形式のトークン・秘密鍵・Webhook URL を探す。
// 検出値は表示せず、ファイル名・行番号・種類だけを出す。誤検知は行末に `secret-scan: allow` を付けて抑止する
// （抑止の追加はレビュー対象）。より詳しい検査には gitleaks（無料）を併用する: `gitleaks dir . --redact`。
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { extname, join } from "node:path";

const patterns = {
  秘密鍵: /-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----/,
  "AWS アクセスキー": /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/,
  "GitHub トークン": /\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b/,
  "Slack トークン": /\bxox[abprs]-[A-Za-z0-9-]{10,}\b/,
  "OpenAI/Anthropic 形式の API キー": /\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}\b/,
  "Google API キー": /\bAIza[0-9A-Za-z_-]{35}\b/,
  "Discord Webhook URL":
    /https:\/\/(?:ptb\.|canary\.)?discord(?:app)?\.com\/api\/webhooks\/\d+\/[A-Za-z0-9_-]{20,}/,
  "Slack Webhook URL": /https:\/\/hooks\.slack\.com\/services\/[A-Za-z0-9/]{20,}/,
  "認証情報付き URL": /\b[a-z][a-z0-9+.-]*:\/\/[^/\s:@]+:[^/\s:@]{6,}@/,
};
const allow = "secret-scan: allow";
const skip = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz"]);

const root = process.argv[2] ?? ".";
const names = execFileSync(
  "git",
  ["-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
  { encoding: "utf8" },
)
  .split("\0")
  .filter((name) => name && !skip.has(extname(name).toLowerCase()) && name !== "package-lock.json");

let count = 0;
for (const name of names) {
  let text;
  try {
    text = readFileSync(join(root, name), "utf8");
  } catch {
    continue;
  }
  text.split(/\r?\n/u).forEach((line, index) => {
    if (line.includes(allow)) return;
    for (const [kind, pattern] of Object.entries(patterns)) {
      if (pattern.test(line)) {
        count += 1;
        console.error(`${name}:${index + 1}: ${kind}の可能性（値は表示しません）`);
      }
    }
  });
}
if (count > 0) {
  console.error(`秘密情報スキャン: ${count} 件を検出しました`);
  process.exit(1);
}
console.log("秘密情報スキャン: 検出なし");
