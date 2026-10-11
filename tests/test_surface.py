"""netease_music 插件面（entry / llm_tool / 合规）冒烟测试。"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pytest.importorskip("plugin.sdk.plugin")

from plugin.plugins.netease_music import NeteaseMusicPlugin  # noqa: E402
from plugin.sdk.plugin.llm_tool import LLM_TOOL_META_ATTR, LlmToolMeta  # noqa: E402

_EXPECTED_TOOLS = {
    "search_songs",
    "play_song",
    "play_random_song",
    "get_lyrics",
    "get_hot_search",
    "get_toplist",
    "get_similar_songs",
    "resolve_and_play",
    "like_song",
    "unlike_song",
    "list_favorites",
    "create_daily_playlist",
    "get_daily_playlist",
    "get_music_preferences",
    "update_music_preferences",
}


def _llm_tool_metas() -> dict:
    metas = {}
    for _, member in inspect.getmembers(NeteaseMusicPlugin):
        meta = getattr(member, LLM_TOOL_META_ATTR, None)
        if isinstance(meta, LlmToolMeta):
            metas[meta.name] = member
    return metas


def test_expected_llm_tools_registered() -> None:
    assert _EXPECTED_TOOLS <= set(_llm_tool_metas())


def test_llm_tool_handlers_are_async() -> None:
    for name, handler in _llm_tool_metas().items():
        assert inspect.iscoroutinefunction(handler), f"llm tool {name} must be async def"


def test_llm_tool_schemas_are_provider_safe() -> None:
    """@llm_tool 的 description/parameters 原样进入模型 function schema，
    只能是纯字符串；tr() 的 $i18n 引用会让所有对话请求 400。"""
    for name, handler in _llm_tool_metas().items():
        meta = getattr(handler, LLM_TOOL_META_ATTR)
        assert isinstance(meta.description, str), f"llm tool {name} description must be str"
        payload = json.dumps(meta.parameters, ensure_ascii=False)
        assert "$i18n" not in payload, f"llm tool {name} parameters must not contain tr() refs"


def test_expected_entries_defined() -> None:
    for entry_id in (
        "test_api",
        "show_status",
        "search_and_play",
        "show_library",
        "save_preferences",
        "summarize_preferences",
    ):
        method = getattr(NeteaseMusicPlugin, entry_id, None)
        assert method is not None, f"missing entry {entry_id}"
        assert inspect.iscoroutinefunction(method), f"entry {entry_id} must be async def"


def test_store_and_ui_surface_declared() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "plugin.toml").read_text(encoding="utf-8")
    assert "[plugin.store]" in manifest, "internal library needs PluginStore"
    assert "[plugin.ui]" in manifest
    assert 'entry = "ui/panel.tsx"' in manifest
    assert (root / "ui" / "panel.tsx").is_file()
    context = getattr(NeteaseMusicPlugin, "main_context", None)
    assert context is not None


def test_daily_playlist_count_window() -> None:
    """每日歌单数量约定：10±3。"""
    from plugin.plugins.netease_music import _DAILY_MAX, _DAILY_MIN, _DAILY_TARGET

    assert (_DAILY_MIN, _DAILY_TARGET, _DAILY_MAX) == (7, 10, 13)


def test_reminder_slot_skips_first_proactive_round() -> None:
    """每日提醒槽位落在前 5 轮主动搭话中的非第 1 轮（2-5）。"""
    from plugin.plugins.netease_music import _REMINDER_SLOT_MAX, _REMINDER_SLOT_MIN

    assert (_REMINDER_SLOT_MIN, _REMINDER_SLOT_MAX) == (2, 5)


def test_proactive_turn_detection() -> None:
    from plugin.plugins.netease_music import _is_proactive_turn

    assert _is_proactive_turn({"turn_type": "proactive"})
    assert _is_proactive_turn({"metadata": {"turn_type": "proactive_chat"}})
    assert _is_proactive_turn({"metadata": {"proactive": True}})
    assert _is_proactive_turn({"metadata": {"had_user_input": False}})
    assert not _is_proactive_turn({"turn_type": "user", "metadata": {"had_user_input": True}})
    assert not _is_proactive_turn({})


def test_timer_watcher_registered() -> None:
    method = getattr(NeteaseMusicPlugin, "proactive_watch", None)
    assert method is not None
    assert inspect.iscoroutinefunction(method)


def test_lifecycle_handlers_defined() -> None:
    for name in ("startup", "shutdown", "on_config_change"):
        method = getattr(NeteaseMusicPlugin, name, None)
        assert method is not None, f"missing lifecycle handler {name}"
        assert inspect.iscoroutinefunction(method)


def test_locale_files_key_consistency() -> None:
    root = Path(__file__).resolve().parents[1]
    key_sets = {}
    for path in sorted((root / "i18n").glob("*.json")):
        key_sets[path.name] = set(json.loads(path.read_text(encoding="utf-8")))
    assert len(key_sets) == 8, f"expected 8 locale files, got {sorted(key_sets)}"
    base = key_sets["zh-CN.json"]
    assert base, "zh-CN.json must not be empty"
    for name, keys in key_sets.items():
        assert keys == base, f"{name} key set differs from zh-CN.json"


def test_attribution_preserved() -> None:
    """MIT 衍生作品：LICENSE 随附、README 开头必须保留来源声明与原作者署名。"""
    root = Path(__file__).resolve().parents[1]
    assert (root / "LICENSE").is_file(), "MIT license text must ship with the plugin"
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "我不能倒霉" in license_text or "Copyright (c)" in license_text
    readme = (root / "README.md").read_text(encoding="utf-8")
    head = readme[:1500]
    assert "来源声明" in head, "README must declare origin at the beginning"
    assert "astrbot_plugin_neteasemusic" in head
    assert "wbndm" in head or "我不能倒霉" in head


def test_module_import_has_no_background_side_effects() -> None:
    """HTTP 会话必须懒创建：import 期不得建连/起线程。"""
    from plugin.plugins.netease_music.core import api

    assert api._session is None, "aiohttp session must be created lazily on first request"
