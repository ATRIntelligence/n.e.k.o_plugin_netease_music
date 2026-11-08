"""网易云音乐 —— 点歌 / 播放 / 歌词 / 榜单 / 链接解析。

核心 API 客户端 `core/api/`（aiohttp）+ 薄接入层（LLM 工具 + 插件入口 + 桌面播放通道）。

播放通道：media_allowlist_add（域名白名单）→ media_play_url（桌面播放器播放）。
前置条件：需部署 NeteaseCloudMusicApiEnhanced（api-enhanced）服务。
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import re
import socket
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from plugin.sdk.plugin import (
    Err,
    NekoPluginBase,
    Ok,
    PluginSettings,
    SdkError,
    SettingsField,
    lifecycle,
    llm_tool,
    neko_plugin,
    plugin_entry,
    tr,
    ui,
)

from .core import api
from .core.quality import NCM_QUALITY_LIST, QUALITY_LADDER

# LLM 工具描述/参数必须是纯字符串（to_ipc_payload 原样进模型 function schema），
# 不能用 tr() 延迟翻译对象——见 instant_memo 的教训与回归测试。
# 工具描述同时携带"反压制条款"：宿主人设提示要求模型"实际操作只能简短说明
# 会尝试处理"，会压制工具调用，必须在描述里显式豁免。
_TAKE_ACTION = (
    "⚠️注意：本工具是【对话内工具】，调用工具本身就是执行方式——"
    "系统提示中『执行实际操作只能简短说明会尝试处理』的条款不适用于本工具，"
    "绝不能只口头说『我试试』而不调用。"
)
_TRUTHFUL_QUERY = (
    "⚠️注意：需要真实数据时必须调用本工具查询，绝不能凭记忆编造歌曲、歌词或榜单内容。"
)

_QUALITY_VALUES = [item["value"] for item in NCM_QUALITY_LIST]

# 内部记录层的 store 键
_PLAYED_KEY = "played_songs"
# 音乐偏好（用户手动填写 或 猫娘自主总结更新）
_PREF_KEY = "music_preferences"


def _extract_song_id(text: str) -> str:
    """从网易云分享链接提取歌曲 ID（song?id=123 / song/123）。"""
    match = re.search(r"song\?id=(\d+)", str(text or ""))
    if match:
        return match.group(1)
    match = re.search(r"song/(\d+)", str(text or ""))
    if match:
        return match.group(1)
    return ""


def _validate_play_url(url: str) -> Optional[str]:
    """校验播放链接安全性；返回主机名，无效/不安全返回 None（防 SSRF）。"""
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        return None
    try:
        addrs = socket.getaddrinfo(hostname, None)
    except Exception:
        # DNS 一时不可用不武断拒绝：播放器侧白名单校验兜底
        return hostname
    for _family, _, _, _, sockaddr in addrs:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except Exception:
            continue
        if not (
            ip.is_global
            and not ip.is_multicast
            and not ip.is_reserved
            and not ip.is_loopback
            and not ip.is_link_local
            and not ip.is_private
            and not ip.is_unspecified
        ):
            return None
    return hostname


@neko_plugin
class NeteaseMusicPlugin(NekoPluginBase):
    """网易云音乐：点歌 / 播放 / 歌词 / 榜单 / 链接解析。"""

    class Settings(PluginSettings):
        """业务配置（plugin.toml 的 [netease_music] 节）— hot 字段会出现在设置面板。"""

        model_config = {"toml_section": "netease_music"}

        api_base: str = SettingsField(
            "http://127.0.0.1:3000",
            hot=True,
            description="api-enhanced 服务地址（需自行部署 NeteaseCloudMusicApiEnhanced）",
        )
        quality: str = SettingsField(
            "auto",
            hot=True,
            description="最高播放音质：auto/jymaster/dolby/sky/vivid/jyeffect/hires/lossless/exhigh/higher/standard",
        )
        unblock: bool = SettingsField(
            True, hot=True, description="VIP/灰歌自动解灰兜底（音质可能降为源站可用）"
        )
        cookie: str = SettingsField(
            "", description="网易云 Cookie（MUSIC_U=...），提供登录态以解锁会员音质"
        )

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.logger = ctx.logger
        self._store_lock = threading.Lock()
        self._settings: Dict[str, Any] = {
            "api_base": "http://127.0.0.1:3000",
            "quality": "auto",
            "unblock": True,
            "cookie": "",
        }

    # ── 生命周期与配置 ──

    @lifecycle(id="startup")
    async def startup(self, **_):
        await self._reload_config()
        # 注入 API 客户端配置访问器（apiBase / defaultCookie）
        api.set_config_getter(self._api_config)
        if not self.store.enabled:
            self.store.enabled = True
            self.logger.warning("PluginStore was disabled at init; force-enabled for internal library")
        self.logger.info(
            "NeteaseMusic started: api_base={} quality={}",
            self._settings["api_base"],
            self._settings["quality"],
        )
        return Ok({
            "status": "ready",
            "api_base": self._settings["api_base"],
        })

    @lifecycle(id="shutdown")
    async def shutdown(self, **_):
        try:
            await api.close_session()
        except Exception:
            pass
        return Ok({"status": "stopped"})

    @lifecycle(id="config_change")
    async def on_config_change(self, **_):
        await self._reload_config()
        return Ok({"status": "config_updated"})

    async def _reload_config(self) -> None:
        cfg = await self.config.dump(timeout=5.0)
        cfg = cfg if isinstance(cfg, dict) else {}
        section = cfg.get("netease_music")
        section = section if isinstance(section, dict) else {}
        merged = dict(self._settings)
        for key in ("api_base", "quality", "unblock", "cookie"):
            if key in section:
                value = section[key]
                try:
                    merged[key] = bool(value) if isinstance(self._settings[key], bool) else str(value)
                except (TypeError, ValueError):
                    pass
        if merged["quality"] not in _QUALITY_VALUES:
            merged["quality"] = "auto"
        self._settings = merged

    def _api_config(self) -> Dict[str, Any]:
        return {
            "apiBase": str(self._settings.get("api_base") or ""),
            "defaultCookie": str(self._settings.get("cookie") or ""),
        }

    # ── 播放通道 ──

    def _push_play(self, url: str, name: str, artist: str) -> Optional[str]:
        """域名白名单 + 桌面播放器播放；返回错误信息或 None。"""
        host = _validate_play_url(url)
        if not host:
            return "播放链接无效或不安全（仅支持公网 http/https 音频链接）"
        allow = self.push_message(
            source="netease_music",
            visibility=["chat"],
            ai_behavior="blind",
            parts=[{"type": "ui_action", "action": "media_allowlist_add", "domains": [host]}],
        )
        if not allow.get("submitted"):
            return f"播放域名白名单提交失败: {allow.get('reason')}"
        play = self.push_message(
            source="netease_music",
            visibility=["chat"],
            ai_behavior="blind",
            parts=[
                {
                    "type": "ui_action",
                    "action": "media_play_url",
                    "url": url,
                    "media_type": "audio",
                    "name": name or "未知歌曲",
                    "artist": artist or "",
                }
            ],
        )
        if not play.get("submitted"):
            return f"播放指令提交失败: {play.get('reason')}"
        return None

    async def _play_song(self, song: Dict[str, Any], level: str = "") -> Dict[str, Any]:
        song_id = song.get("id") or 0
        use_level = (level or "").strip() or str(self._settings.get("quality") or "auto")
        if use_level not in _QUALITY_VALUES:
            use_level = "auto"
        try:
            url_data = await api.song_url_best(
                song_id,
                level=use_level,
                unblock_fallback=bool(self._settings.get("unblock", True)),
            )
        except api.ApiError as e:
            return {"played": False, "reason": str(e)}
        url = str((url_data or {}).get("url") or "")
        if not url:
            return {"played": False, "reason": "该曲无可用播放链接（可能无版权或需要更高会员权限）"}
        err = await asyncio.to_thread(
            self._push_play, url, str(song.get("name") or ""), str(song.get("artist") or "")
        )
        if err:
            return {"played": False, "reason": err}
        self.logger.info("playing: id={} name={} level={}", song_id, song.get("name"), use_level)
        # 猫娘播放记录（仅 N.E.K.O 内部记录，不与网易云同步）
        try:
            await asyncio.to_thread(self._record_played_sync, song, use_level)
        except Exception:
            self.logger.warning("record played song failed (non-fatal)")
        return {
            "played": True,
            "id": song_id,
            "name": song.get("name", ""),
            "artist": song.get("artist", ""),
            "album": song.get("album", ""),
            "quality": use_level,
            "note": "音乐已开始在桌面播放器播放。" + _TAKE_ACTION,
        }

    async def _resolve_song(self, keyword: Any, song_id: Any) -> Dict[str, Any]:
        """按 id 或关键词解析出一首歌。"""
        if song_id:
            details = await api.song_detail(str(song_id).strip())
            return details[0] if details else {}
        keyword = str(keyword or "").strip()
        if not keyword:
            return {}
        results = await api.search(keyword, type_=1, limit=5)
        return results[0] if results else {}

    # ── LLM 工具（纯字符串 schema + 反压制条款）──

    @llm_tool(
        name="search_songs",
        description=(
            "按关键词搜索网易云音乐歌曲，返回歌曲 ID、歌名、歌手、专辑、时长列表（只查不播）。"
            + _TRUTHFUL_QUERY
        ),
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "歌曲名、歌手或专辑关键词。"},
                "limit": {"type": "integer", "description": "返回条数，1-20，默认 5。"},
            },
            "required": ["keyword"],
        },
    )
    async def search_songs(self, *, keyword: Any = None, limit: Any = 5, **_):
        keyword = str(keyword or "").strip()
        if not keyword:
            return {"status": "error", "note": "keyword 不能为空"}
        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 5
        try:
            results = await api.search(keyword, type_=1, limit=limit)
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        return {"status": "ok", "count": len(results), "songs": results}

    @llm_tool(
        name="play_song",
        description=(
            "点歌并立即在桌面播放器播放：给 song_id 直接播放该曲；只给 keyword 时搜索并播放第一首。"
            + _TAKE_ACTION
        ),
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "歌曲名/歌手关键词（与 song_id 二选一）。"},
                "song_id": {"type": "string", "description": "网易云歌曲 ID（优先于 keyword）。"},
                "level": {
                    "type": "string",
                    "enum": _QUALITY_VALUES,
                    "description": "音质档位，省略则用插件配置的默认档位。",
                },
            },
        },
    )
    async def play_song(self, *, keyword: Any = "", song_id: Any = "", level: Any = "", **_):
        try:
            song = await self._resolve_song(keyword, song_id)
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        if not song:
            return {"status": "error", "note": "没有找到匹配的歌曲，请换个关键词或提供 song_id"}
        try:
            result = await self._play_song(song, str(level or ""))
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        result["status"] = "ok" if result.get("played") else "error"
        return result

    @llm_tool(
        name="play_random_song",
        description=(
            "随机播放一首歌（来首歌）：优先个人 FM（需 Cookie 登录），未登录时用推荐新歌。"
            + _TAKE_ACTION
        ),
        parameters={"type": "object", "properties": {}},
    )
    async def play_random_song(self, **_):
        try:
            songs = await api.personal_fm()
            if not songs:
                songs = await api.recommend_newsong(limit=10)
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        if not songs:
            return {"status": "error", "note": "当前没有可播放的推荐歌曲"}
        song = random.choice(songs)
        try:
            result = await self._play_song(song)
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        result["status"] = "ok" if result.get("played") else "error"
        return result

    @llm_tool(
        name="get_lyrics",
        description=(
            "获取歌曲歌词（含翻译，可选逐字歌词）：给 song_id 或 keyword。" + _TRUTHFUL_QUERY
        ),
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "歌曲名/歌手关键词（与 song_id 二选一）。"},
                "song_id": {"type": "string", "description": "网易云歌曲 ID（优先于 keyword）。"},
                "word_by_word": {"type": "boolean", "description": "true 时附带逐字歌词（默认 false）。"},
            },
        },
    )
    async def get_lyrics(self, *, keyword: Any = "", song_id: Any = "", word_by_word: Any = False, **_):
        try:
            song = await self._resolve_song(keyword, song_id)
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        if not song:
            return {"status": "error", "note": "没有找到匹配的歌曲"}
        sid = song.get("id") or 0
        try:
            lrc_data = await api.lyric(sid)
            payload: Dict[str, Any] = {
                "status": "ok",
                "id": sid,
                "name": song.get("name", ""),
                "artist": song.get("artist", ""),
                "lrc": (lrc_data or {}).get("lrc", ""),
                "translation": (lrc_data or {}).get("tlyric", ""),
            }
            if word_by_word:
                try:
                    payload["yrc"] = await api.lyric_new(sid)
                except Exception:
                    payload["yrc"] = {}
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        return payload

    @llm_tool(
        name="get_hot_search",
        description="获取网易云音乐热搜榜（当前热门搜索关键词）。" + _TRUTHFUL_QUERY,
        parameters={"type": "object", "properties": {}},
    )
    async def get_hot_search(self, **_):
        try:
            results = await api.hot_search()
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        return {"status": "ok", "count": len(results), "hot_search": results}

    @llm_tool(
        name="get_toplist",
        description=(
            "获取网易云排行榜：不传 chart 时返回榜单列表；传 chart（榜单名或 id）时返回该榜单曲目。"
            + _TRUTHFUL_QUERY
        ),
        parameters={
            "type": "object",
            "properties": {
                "chart": {
                    "type": "string",
                    "description": "榜单名（如『飙升榜』『新歌榜』）或榜单 id；留空返回榜单列表。",
                },
                "limit": {"type": "integer", "description": "曲目条数，1-50，默认 20。"},
            },
        },
    )
    async def get_toplist(self, *, chart: Any = "", limit: Any = 20, **_):
        try:
            limit = max(1, min(int(limit), 50))
        except (TypeError, ValueError):
            limit = 20
        chart_text = str(chart or "").strip()
        charts = await api.toplist()
        if not chart_text:
            return {"status": "ok", "count": len(charts), "charts": charts}
        target = None
        for item in charts:
            if chart_text == str(item.get("id", "")) or chart_text in str(item.get("name", "")):
                target = item
                break
        if target is None:
            return {"status": "error", "note": f"没有找到名为『{chart_text}』的榜单", "charts": charts}
        songs = await api.top_detail(target.get("id"), limit=limit)
        return {"status": "ok", "chart": target.get("name", chart_text), "count": len(songs), "songs": songs}

    @llm_tool(
        name="get_similar_songs",
        description="获取与指定歌曲相似的推荐歌曲（给 song_id 或 keyword）。" + _TRUTHFUL_QUERY,
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "歌曲名/歌手关键词（与 song_id 二选一）。"},
                "song_id": {"type": "string", "description": "网易云歌曲 ID（优先于 keyword）。"},
            },
        },
    )
    async def get_similar_songs(self, *, keyword: Any = "", song_id: Any = "", **_):
        try:
            song = await self._resolve_song(keyword, song_id)
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        if not song:
            return {"status": "error", "note": "没有找到匹配的歌曲"}
        try:
            results = await api.simi_songs(song.get("id") or 0, limit=10)
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        return {
            "status": "ok",
            "based_on": {"id": song.get("id"), "name": song.get("name", "")},
            "count": len(results),
            "songs": results,
        }

    @llm_tool(
        name="resolve_and_play",
        description=(
            "解析网易云音乐分享链接/短链（music.163.com、163cn.tv 等）并立即播放其中的歌曲。"
            + _TAKE_ACTION
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "网易云歌曲/歌单分享链接或短链。"},
            },
            "required": ["url"],
        },
    )
    async def resolve_and_play(self, *, url: Any = "", **_):
        text = str(url or "").strip()
        if not text:
            return {"status": "error", "note": "url 不能为空"}
        try:
            expanded = await api.expand_short_links(text)
        except Exception:
            expanded = text
        song_id = _extract_song_id(expanded)
        if not song_id:
            return {
                "status": "error",
                "note": "链接中没有识别出歌曲 ID（支持 music.163.com/song?id=... 形式与 163cn.tv 短链）",
            }
        try:
            song = await self._resolve_song("", song_id)
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        if not song:
            return {"status": "error", "note": f"链接对应的歌曲不存在（id={song_id}）"}
        try:
            result = await self._play_song(song)
        except api.ApiError as e:
            return {"status": "error", "note": str(e)}
        result["status"] = "ok" if result.get("played") else "error"
        return result

    # ── 内部记录层（PluginStore；仅 N.E.K.O 内部保存）──

    def _store_get_sync(self, key: str, default: Any) -> Any:
        if not self.store.enabled:
            return default
        try:
            return self.store._read_value(key, default)
        except Exception as exc:
            self.logger.warning("store get failed key={}: {}", key, exc)
            return default

    def _store_set_sync(self, key: str, value: Any) -> None:
        if not self.store.enabled:
            raise SdkError("PluginStore 未启用，无法保存内部歌单数据")
        try:
            self.store._write_value(key, value)
        except Exception as exc:
            raise SdkError(f"保存内部歌单数据失败: {exc}") from exc

    @staticmethod
    def _song_compact(song: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
        item = {
            "id": song.get("id") or 0,
            "name": str(song.get("name") or ""),
            "artist": str(song.get("artist") or ""),
            "album": str(song.get("album") or ""),
        }
        item.update(extra)
        return item

    def _record_played_sync(self, song: Dict[str, Any], quality: str) -> None:
        """猫娘播放记录：追加到内部播放歌单（不与网易云同步），最多保留 200 条。"""
        with self._store_lock:
            played = self._store_get_sync(_PLAYED_KEY, [])
            played = list(played) if isinstance(played, list) else []
            played.append(self._song_compact(
                song, played_at=time.time(), quality=str(quality or "auto")
            ))
            self._store_set_sync(_PLAYED_KEY, played[-200:])

    def _library_snapshot_sync(self) -> Dict[str, Any]:
        with self._store_lock:
            played = self._store_get_sync(_PLAYED_KEY, [])
        played = list(played) if isinstance(played, list) else []
        return {"played": played}

    # ── 音乐偏好（手动填写 / 猫娘自主总结）──

    def _get_prefs_sync(self) -> Dict[str, Any]:
        with self._store_lock:
            pref = self._store_get_sync(_PREF_KEY, {})
        return dict(pref) if isinstance(pref, dict) else {}

    def _save_prefs_sync(self, text: str, updated_by: str) -> Dict[str, Any]:
        payload = {
            "text": str(text or "").strip(),
            "updated_at": time.time(),
            "updated_by": str(updated_by or "user"),
        }
        with self._store_lock:
            self._store_set_sync(_PREF_KEY, payload)
        self.logger.info("music preferences updated by {}", payload["updated_by"])
        return payload

    @llm_tool(
        name="get_music_preferences",
        description=(
            "读取用户的音乐偏好记录（口味、常听歌手、场景习惯等）。"
            "推荐歌曲前可先调用本工具了解偏好。" + _TRUTHFUL_QUERY
        ),
        parameters={"type": "object", "properties": {}},
    )
    async def get_music_preferences(self, **_):
        pref = await asyncio.to_thread(self._get_prefs_sync)
        return {
            "status": "ok",
            "preferences": str(pref.get("text") or ""),
            "updated_at": pref.get("updated_at", 0),
            "updated_by": pref.get("updated_by", ""),
            "note": "偏好为空时可根据对话与播放记录总结后用 update_music_preferences 写入。",
        }

    @llm_tool(
        name="update_music_preferences",
        description=(
            "更新用户的音乐偏好记录：可以基于与用户的对话、播放记录"
            "自主总结出偏好（口味/常听歌手/场景/禁忌），也可以在用户明确表达偏好时直接记录。"
            "每次全量覆盖写入。" + _TAKE_ACTION
        ),
        parameters={
            "type": "object",
            "properties": {
                "preferences": {
                    "type": "string",
                    "description": "完整的音乐偏好描述文本（覆盖式写入），如『喜欢日系摇滚和纯音乐，常听 YOASOBI，学习时偏好无人声』。",
                },
                "reason": {"type": "string", "description": "本次更新的依据（可选），如『根据最近播放记录总结』。"},
            },
            "required": ["preferences"],
        },
    )
    async def update_music_preferences(self, *, preferences: Any = "", reason: Any = "", **_):
        text = str(preferences or "").strip()
        if not text:
            return {"status": "error", "note": "preferences 不能为空"}
        if len(text) > 2000:
            return {"status": "error", "note": "preferences 过长（上限 2000 字），请精简后重试"}
        try:
            saved = await asyncio.to_thread(self._save_prefs_sync, text, "ai")
        except SdkError as e:
            return {"status": "error", "note": str(e)}
        return {
            "status": "ok",
            "preferences": saved["text"],
            "reason": str(reason or ""),
            "note": (
                "音乐偏好记录已更新（AI 总结）。"
                "后续推荐歌曲时应遵循这份偏好。" + _TAKE_ACTION
            ),
        }

    # ── 可调用入口（Plugin Manager / Agent）──

    @plugin_entry(
        id="test_api",
        name=tr("entry.test_api.name", default="测试 API 连通性"),
        description=tr(
            "entry.test_api.description",
            default="测试 api-enhanced 服务是否可达，并返回连通状态。",
        ),
        llm_result_fields=["status", "message"],
    )
    async def test_api(self, **_):
        try:
            results = await api.hot_search()
            return Ok({
                "status": "ok",
                "message": f"API 连接正常（热搜榜返回 {len(results)} 条）",
                "api_base": self._settings.get("api_base", ""),
            })
        except Exception as e:
            return Err(SdkError(
                f"API 连接失败：{e}（请检查 [netease_music].api_base 与 api-enhanced 服务）"
            ))

    @plugin_entry(
        id="show_status",
        name=tr("entry.show_status.name", default="查看音乐插件状态"),
        description=tr(
            "entry.show_status.description",
            default="显示当前 API 地址、音质档位、登录态与配置摘要。",
        ),
        llm_result_fields=["api_base", "quality", "logged_in"],
    )
    async def show_status(self, **_):
        logged_in = bool(str(self._settings.get("cookie") or "").strip())
        return Ok({
            "api_base": self._settings.get("api_base", ""),
            "quality": self._settings.get("quality", "auto"),
            "unblock": bool(self._settings.get("unblock", True)),
            "logged_in": logged_in,
            "quality_ladder": QUALITY_LADDER,
            "message": (
                "已登录（Cookie 生效）"
                if logged_in
                else "未登录：可点歌播放公开音源，会员音质需要配置 Cookie"
            ),
        })

    @plugin_entry(
        id="search_and_play",
        name=tr("entry.search_and_play.name", default="点歌播放"),
        description=tr(
            "entry.search_and_play.description",
            default="按关键词搜索并立即在桌面播放器播放第一首匹配歌曲。",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": tr(
                        "entry.search_and_play.param.keyword", default="歌曲名或歌手关键词。"
                    ),
                },
            },
            "required": ["keyword"],
        },
        llm_result_fields=["played", "name", "artist"],
    )
    async def search_and_play(self, keyword: str = "", **_):
        keyword = str(keyword or "").strip()
        if not keyword:
            return Err(SdkError("keyword 不能为空"))
        try:
            results = await api.search(keyword, type_=1, limit=5)
        except api.ApiError as e:
            return Err(SdkError(str(e)))
        if not results:
            return Err(SdkError(f"没有找到与『{keyword}』匹配的歌曲"))
        try:
            result = await self._play_song(results[0])
        except api.ApiError as e:
            return Err(SdkError(str(e)))
        if not result.get("played"):
            return Err(SdkError(str(result.get("reason") or "播放失败")))
        return Ok(result)

    @plugin_entry(
        id="show_library",
        name=tr("entry.show_library.name", default="查看音乐库"),
        description=tr(
            "entry.show_library.description",
            default="查看猫娘播放记录（N.E.K.O 内部记录）。",
        ),
        llm_result_fields=["played_count"],
    )
    async def show_library(self, **_):
        snapshot = await asyncio.to_thread(self._library_snapshot_sync)
        return Ok({
            "played_count": len(snapshot["played"]),
            "played_recent": snapshot["played"][-20:],
        })

    @ui.action(
        id="save_preferences",
        label=tr("actions.save_preferences.label", default="保存"),
        tone="primary",
        group="preferences",
        order=10,
        refresh_context=True,
    )
    @plugin_entry(
        id="save_preferences",
        name=tr("entry.save_preferences.name", default="保存音乐偏好"),
        description=tr(
            "entry.save_preferences.description",
            default="手动填写/修改用户的音乐偏好记录（全量覆盖）。",
        ),
        input_schema={
            "type": "object",
            "properties": {
                "preferences": {
                    "type": "string",
                    "description": tr(
                        "entry.save_preferences.param.preferences",
                        default="完整的音乐偏好描述文本（覆盖式保存）。",
                    ),
                },
            },
            "required": ["preferences"],
        },
        llm_result_fields=["saved", "preferences"],
    )
    async def save_preferences(self, preferences: str = "", **_):
        text = str(preferences or "").strip()
        if not text:
            return Err(SdkError("preferences 不能为空"))
        if len(text) > 2000:
            return Err(SdkError("preferences 过长（上限 2000 字）"))
        try:
            saved = await asyncio.to_thread(self._save_prefs_sync, text, "user")
        except SdkError as e:
            return Err(SdkError(str(e)))
        return Ok({
            "saved": True,
            "preferences": saved["text"],
            "message": "音乐偏好已保存（手动填写）",
        })

    @ui.action(
        id="summarize_preferences",
        label=tr("actions.summarize_preferences.label", default="让猫娘总结"),
        tone="info",
        group="preferences",
        order=20,
        refresh_context=True,
    )
    @plugin_entry(
        id="summarize_preferences",
        name=tr("entry.summarize_preferences.name", default="猫娘总结音乐偏好"),
        description=tr(
            "entry.summarize_preferences.description",
            default="请猫娘根据对话与播放记录自主总结音乐偏好并写入。",
        ),
        llm_result_fields=["requested"],
    )
    async def summarize_preferences(self, **_):
        cue = (
            "======[待执行任务 · 音乐偏好总结]======\n"
            "这不是一条需要口头回应的聊天消息，而是一个待执行任务。"
            "请根据你与 {MASTER_NAME} 的对话记忆与最近的播放记录，"
            "总结出 {MASTER_NAME} 的音乐偏好（口味、常听歌手、场景习惯、禁忌），"
            "**调用 update_music_preferences 工具**写入。\n"
            "⚠️执行要求：必须真正调用工具完成写入，绝不能只口头答应或说『我试试』；"
            "通知模板要求的『简洁回应』不适用于本任务。"
        )
        result = self.push_message(
            source="netease_music",
            visibility=[],
            ai_behavior="read",
            parts=[{"type": "text", "text": cue}],
            priority=5,
            metadata={"event_type": "preferences_summary_request"},
        )
        if not result.get("submitted"):
            return Err(SdkError(f"请求发送失败: {result.get('reason')}"))
        pref = await asyncio.to_thread(self._get_prefs_sync)
        return Ok({
            "requested": True,
            "preferences": str(pref.get("text") or ""),
            "message": "已请猫娘总结偏好，将在下一轮对话时执行并写入（可在面板刷新查看）",
        })

    # ── Hosted UI（基础面板：偏好设置 / 播放记录）──

    @ui.context(id="main", title=tr("ui.main.title", default="网易云音乐"))
    async def main_context(self):
        snapshot = await asyncio.to_thread(self._library_snapshot_sync)
        pref = await asyncio.to_thread(self._get_prefs_sync)
        return {
            "preferences": {
                "text": str(pref.get("text") or ""),
                "updated_at": _fmt_ts(pref.get("updated_at")),
                "updated_by": str(pref.get("updated_by") or ""),
            },
            "played": [
                {
                    "name": s.get("name", ""),
                    "artist": s.get("artist", ""),
                    "played_at": _fmt_ts(s.get("played_at")),
                }
                for s in reversed(snapshot["played"][-20:])
            ],
        }


def _fmt_ts(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value)).strftime("%m-%d %H:%M")
    except Exception:
        return ""
