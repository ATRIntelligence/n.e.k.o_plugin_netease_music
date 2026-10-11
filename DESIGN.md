# 网易云音乐 (N.E.K.O 移植版) Design Brief

## Identity Lock
- plugin_id: `netease_music`
- folder: `plugin/plugins/netease_music/`
- name: 网易云音乐
- entry: `plugin.plugins.netease_music:NeteaseMusicPlugin`
- main class: `NeteaseMusicPlugin`

## Purpose

对猫娘说一句话即可点歌、播放、查歌词/榜单、解析分享链接。桌面播放器出声。

## Package Type and Capabilities
- package type: `plugin`
- capabilities:
  - LLM 工具（`@llm_tool`，纯字符串 schema + 反压制条款）：`search_songs` /
    `play_song` / `play_random_song` / `get_lyrics` / `get_hot_search` /
    `get_toplist` / `get_similar_songs` / `resolve_and_play`
  - 可调用入口（`@plugin_entry`）：`test_api` / `show_status` / `search_and_play`
  - 生命周期：`startup`（注入 api 配置访问器）/ `shutdown`（关 HTTP 会话）/ `config_change`
  - 播放通道：`media_allowlist_add`（域名白名单，SSRF 校验）→ `media_play_url`
- inferred architecture: `core/api/`（原作 MIT 的 aiohttp API 客户端，仅替换日志导入）
  + 本插件薄接入层（工具/入口/播放推送）。

## First Version Scope

- 点歌/搜索、直接播放（关键词或 ID）、来首歌、歌词（含逐字）、热搜、排行榜、
  相似歌曲、链接解析播放；音质自适配/解灰；API 连通性自检。
- 配置：`[netease_music]`（api_base / quality / unblock / cookie），hot 字段进设置面板。

## Out of Scope（原插件裁剪记录，详见 README 删增对照）

- 多平台消息投递（QQ 官方/微信/TG/钉钉/飞书/KOOK/Discord/aiocqhttp 全套适配）
- 语音/文件双通道投递、ffmpeg 压缩、QQ 分片上传、OneBot 原生卡片
- HTML 图片卡片渲染（Playwright + 12 套模板）
- 会话式选歌列表（#ncm听N / 听所有）
- 扫码登录（改 cookie 配置）、账号类指令（日推/红心/签到/云盘等）
- 长尾探索指令（banner/电台/MV 榜/新碟榜/歌单分类等）
- 帮助/设置/状态 HTML 面板

## Inferred Technical Needs
- plugin.toml sections: `[plugin]`、`[plugin.sdk]`、`[plugin.author]`、`[plugin.i18n]`、
  `[plugin_runtime]`、`[netease_music]`
- SDK surfaces: `NekoPluginBase`、`neko_plugin`、`plugin_entry`、`llm_tool`、`lifecycle`、
  `tr`、`Ok`/`Err`/`SdkError`、`PluginSettings`/`SettingsField`、`push_message`（v2 parts）
- 外部依赖：宿主自带 `aiohttp`（不 vendor）；外部服务 NeteaseCloudMusicApiEnhanced
- 许可：MIT 衍生作品，LICENSE 随附，README 开头来源/改动声明

## Read Context Plan

- `.agent/skills/neko-plugin/**`、`plugin/PLUGIN_DEVELOPMENT_GUIDE.md`
- 原作 `N.E.K.O迁移插件/music/astrbot_plugin_neteasemusic-*/`（功能与 API 来源）
- `plugin/plugins/music_pusher/`（media_play_url 播放与白名单先例）
- `plugin/plugins/instant_memo/`（工具 schema 纯字符串 + 反压制条款的既定教训）

## Write Workspace
`plugin/plugins/netease_music/`

## Risk Follow-ups

- `@llm_tool` 描述/参数严禁 `tr()` 对象（回归测试守卫）；工具描述含反压制条款。
- 播放 URL 校验（http/https + 公网单播）防 SSRF；白名单先行再播。
- API 会话生命周期：shutdown 时 `close_session()`。
