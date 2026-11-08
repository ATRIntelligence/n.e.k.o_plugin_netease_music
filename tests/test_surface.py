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

_neko_mod = pytest.importorskip("plugin.plugins.netease_music")
_llm_tool_mod = pytest.importorskip("plugin.sdk.plugin.llm_tool")
NeteaseMusicPlugin = _neko_mod.NeteaseMusicPlugin
LLM_TOOL_META_ATTR = _llm_tool_mod.LLM_TOOL_META_ATTR
LlmToolMeta = _llm_tool_mod.LlmToolMeta

_EXPECTED_TOOLS = {
    "search_songs",
    "play_song",
    "play_random_song",
    "get_lyrics",
    "get_hot_search",
    "get_toplist",
    "get_similar_songs",
    "resolve_and_play",
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


def test_license_and_readme_surface() -> None:
    """LICENSE 全文随插件分发；README 保持无版权署名。"""
    root = Path(__file__).resolve().parents[1]
    assert (root / "LICENSE").is_file(), "MIT license text must ship with the plugin"
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "Copyright" not in readme
    assert "©" not in readme


def test_module_import_has_no_background_side_effects() -> None:
    """HTTP 会话必须懒创建：import 期不得建连/起线程。"""
    from plugin.plugins.netease_music.core import api

    assert api._session is None, "aiohttp session must be created lazily on first request"
