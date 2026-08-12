from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).parent.parent
CHECK_SCRIPT = ROOT_DIR / "scripts" / "check-claude-updates.py"
README = ROOT_DIR / "README.md"
EXPECTED_MODEL = "openai/gpt-oss-120b"

sys.path.insert(0, str(CHECK_SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("check_updates_model", CHECK_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECK_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK_MODULE)


def test_supported_groq_model_is_configured() -> None:
    """廃止予定モデルへ戻らないよう、利用モデルIDを固定する。"""
    tree = ast.parse(CHECK_SCRIPT.read_text(encoding="utf-8"))
    model_value = None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "LLM_MODEL"
            for target in node.targets
        ):
            model_value = ast.literal_eval(node.value)
            break

    assert model_value == EXPECTED_MODEL


def test_readme_matches_configured_groq_model() -> None:
    """運用ドキュメントに実装と同じモデルIDを記載する。"""
    assert EXPECTED_MODEL in README.read_text(encoding="utf-8")


def build_checker_with_models(model_ids: list[str]) -> object:
    """モデル一覧APIだけを備えたテスト用チェッカーを作る。"""
    checker = object.__new__(CHECK_MODULE.ReleaseChecker)
    checker.client = SimpleNamespace(
        models=SimpleNamespace(
            list=lambda: SimpleNamespace(
                data=[SimpleNamespace(id=model_id) for model_id in model_ids]
            )
        )
    )
    checker._call_groq_api = lambda operation, _name: operation()
    return checker


def test_model_preflight_accepts_configured_model() -> None:
    """設定モデルが利用可能なら事前確認を通過する。"""
    checker = build_checker_with_models([EXPECTED_MODEL])

    checker.validate_groq_authentication()


def test_model_preflight_rejects_unavailable_model() -> None:
    """設定モデルが一覧になければレポート処理前に失敗する。"""
    checker = build_checker_with_models(["openai/gpt-oss-20b"])

    with pytest.raises(
        CHECK_MODULE.GroqModelUnavailableError,
        match=EXPECTED_MODEL,
    ):
        checker.validate_groq_authentication()


def test_run_aborts_before_release_fetch_when_model_validation_fails() -> None:
    """モデル確認失敗時はリリース取得前に処理を中断する。"""
    checker = object.__new__(CHECK_MODULE.ReleaseChecker)
    checker.get_last_checked_version = lambda: "v2.1.228"
    checker.validate_groq_authentication = lambda: (_ for _ in ()).throw(
        CHECK_MODULE.GroqModelUnavailableError("モデルを利用できません")
    )
    fetch_calls: list[str | None] = []
    checker.fetch_releases = lambda version: fetch_calls.append(version) or []

    with pytest.raises(SystemExit) as exit_info:
        checker.run()

    assert exit_info.value.code == 1
    assert fetch_calls == []
