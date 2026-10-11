# 网易云音乐（N.E.K.O 移植版）

> **来源声明 / 改动说明**
>
> - **来源**：本插件移植自 **wbndm（我不能倒霉）** 的 AstrBot 插件
>   [`astrbot_plugin_neteasemusic`](https://github.com/wbndmqaq/astrbot_plugin_neteasemusic) v2.0.5。
> - **许可**：原作为 **MIT License，Copyright (c) 2026 我不能倒霉**。本衍生作品依 MIT 条款分发，
>   原版权声明与许可全文随附于 [LICENSE](LICENSE)，原作者署名保留。
> - **改动**：核心 API 客户端（`core/api/`）沿用原作实现（仅将日志导入替换为标准库
>   logging，接口行为未改动）；接入层按 N.E.K.O 插件模型**重写**（LLM 工具 + 插件入口 +
>   桌面播放通道），消息投递与卡片渲染等 AstrBot 平台层未移植（见下方删增对照）。

**主要功能**——对猫娘说"放首晴天"、"找周杰伦的歌"、"这歌歌词是什么"即可：

- **点歌播放**：关键词搜索直接播放 / 按歌曲 ID 播放，音质自适配（`auto` 按账号权限
  逐级回退，支持 jymaster/dolby/sky/vivid/hires/lossless 等 11 档）；
- **来首歌**：随机推荐（个人 FM，未登录回退推荐新歌）；
- **歌词查询**：歌词 + 翻译，可选逐字歌词（yrc）；
- **榜单与发现**：热搜榜、排行榜（飙升/新歌/原创等）、相似歌曲推荐；
- **链接解析播放**：粘贴网易云分享链接/`163cn.tv` 短链，自动展开并播放；
- **解灰兜底**：VIP/灰歌自动尝试可用音源（`unblock`，音质可能降级）。

## 删除 / 增加的功能对照

### 删除（AstrBot/群聊平台专属，N.E.K.O 桌面场景不需要）

- **多平台消息投递**：QQ 官方 / 微信 / Telegram / 钉钉 / 飞书 / KOOK / Discord /
  aiocqhttp 全部适配层（含合并消息、QQ 官方分片上传、OneBot 原生音乐卡片）
- **语音/文件双通道投递**：Record 语音、File 文件、ffmpeg 压缩兜底（N.E.K.O 播放器
  直接播放 URL，无需下载转码投递）
- **HTML 图片卡片**：Playwright 渲染引擎 + 12 套 HTML 模板（列表/详情/歌词/帮助等）
- **会话式选歌列表**：`#ncm听N` / `#ncm听所有` / 列表展开交互（改为直接播放）
- **扫码登录**：二维码生成与轮询（改为 `cookie` 配置项直填）
- **账号类指令**：日推 / 我喜欢的 / 红心 / 签到 / 云盘 / 最近播放 / 听歌排行 /
  我的歌单 / 历史日推（API 层保留，接入层未暴露）
- **长尾探索指令**：banner / 电台 / MV 榜 / 新碟榜 / 歌单分类 / 精品歌单 / 歌单评论 /
  专辑评论等（API 层保留，接入层未暴露）

### 增加（N.E.K.O 适配）

- **13 个 LLM 工具**：`search_songs` / `play_song` / `play_random_song` / `get_lyrics` /
  `get_hot_search` / `get_toplist` / `get_similar_songs` / `resolve_and_play` /
  **`like_song`（收藏）/ `unlike_song`（取消收藏）/ `list_favorites`** /
  **`create_daily_playlist`（每日歌单）/ `get_daily_playlist`**，带防压制调用约定
- **收藏与网易云同步**：收藏/取消收藏同时写入 N.E.K.O 本地收藏夹，并在配置了
  `cookie` 时同步网易云红心（我喜欢的音乐）；未配置 Cookie 时仅本地收藏并如实告知
- **猫娘播放歌单**：每次猫娘播放的歌曲自动记入内部播放记录（最近 200 条），
  **仅 N.E.K.O 内部保存，不与网易云同步**
- **偏好每日歌单**：猫娘根据用户偏好（口味/常听歌手/心情场景）挑选歌曲生成
  每日歌单，**每天 10±3 首（7–13，目标 10）**，存于内部记录（保留最近 30 天）。
  **插件启动时自动向猫娘请求生成**（今日歌单不存在时）；并在**每日前 5 轮主动搭话中
  的随机一轮（跳过第 1 轮）**发送歌单提醒——通过会话总线的主动搭话轮标记计数实现，
  主动搭话过少时按兜底窗口（6 小时）在第 ≥2 轮发送
- **偏好设置**：面板内可手动填写音乐偏好；也可点"让猫娘总结"由猫娘根据对话、
  播放记录、收藏**自主总结**后写入（`update_music_preferences` 工具）。偏好记录
  会作为每日歌单生成的选歌依据（生成请求 cue 自动携带）
- **基础 Hosted UI 面板**：偏好设置 / 今日歌单 / 播放记录 / 本地收藏（描述性文案隐藏）
- **4 个插件入口**：`test_api`（连通性自检）/ `show_status`（配置与登录态）/
  `search_and_play`（手动点歌）/ `show_library`（查看音乐库）
- **桌面播放通道**：`media_allowlist_add` 域名白名单（含 SSRF 防护校验）→
  `media_play_url` 桌面播放器播放
- **配置节** `[netease_music]`（hot 字段出现在设置面板）：`api_base` / `quality` /
  `unblock` / `cookie`
- 8 语言 i18n、单元测试、市场打包支持

### 保留（适配后等价能力）

点歌搜索、直接播放、来首歌、歌词/逐字歌词、热搜、排行榜、相似歌曲、
链接解析播放、音质自适配与解灰、API 连通性测试。

## 前置条件

1. **部署 NeteaseCloudMusicApiEnhanced（api-enhanced）服务**并保持运行
   （Node 项目，参见原作 README 的部署章节），默认地址 `http://127.0.0.1:3000`；
2. 在插件配置 `[netease_music].api_base` 中填入服务地址；
3. （可选）在 `cookie` 中填入网易云 `MUSIC_U=...` 以解锁会员音质与账号能力。

## 配置（plugin.toml 的 `[netease_music]` 节）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `api_base` | `http://127.0.0.1:3000` | api-enhanced 服务地址 |
| `quality` | `auto` | 最高播放音质（auto/jymaster/dolby/sky/vivid/jyeffect/hires/lossless/exhigh/higher/standard） |
| `unblock` | `true` | VIP/灰歌解灰兜底（音质可能降为源站可用） |
| `cookie` | 空 | 网易云 Cookie（`MUSIC_U=...`），登录态 |

## 使用示例

对猫娘说：

- "放一首周杰伦的晴天" → `play_song`
- "有没有和这首歌类似的" → `get_similar_songs`
- "这首歌的歌词" → `get_lyrics`
- "现在热搜上有什么" → `get_hot_search`
- "https://music.163.com/#/song?id=186016" → `resolve_and_play`
- "收藏这首歌" / "取消收藏" → `like_song` / `unlike_song`（配置 Cookie 后同步网易云红心）
- "根据我的口味生成今天的歌单" → `create_daily_playlist`（猫娘挑 10±3 首）
- "今天歌单里有什么" → `get_daily_playlist`

插件详情页的 **管理面板** 可查看：今日每日歌单、猫娘播放记录（内部记录）、本地收藏。

## Development

本插件位于：

```text
N.E.K.O/plugin/plugins/netease_music
```

在 N.E.K.O 仓库根目录执行：

```bash
uv run neko-plugin check netease_music
uv run neko-plugin check netease_music --release
```

插件本地测试（使用项目 uv 环境，仓库根目录运行）：

```bash
uv run python -m pytest plugin/plugins/netease_music/tests -q
```

Python 运行时依赖为宿主自带的 `aiohttp`（与仓库内其他插件一致，不单独 vendor）。

## Entry

```toml
entry = "plugin.plugins.netease_music:NeteaseMusicPlugin"
```

## 许可

本插件为 MIT 许可的衍生作品：`Copyright (c) 2026 我不能倒霉`（原作），
许可全文见 [LICENSE](LICENSE)。
