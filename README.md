# 网易云音乐

**主要功能**——对猫娘说"放首晴天"、"找周杰伦的歌"、"这歌歌词是什么"即可：

- **点歌播放**：关键词搜索直接播放 / 按歌曲 ID 播放，音质自适配（`auto` 按账号权限
  逐级回退，支持 jymaster/dolby/sky/vivid/hires/lossless 等 11 档）
- **来首歌**：随机推荐（个人 FM，未登录回退推荐新歌）
- **歌词查询**：歌词 + 翻译，可选逐字歌词（yrc）
- **榜单与发现**：热搜榜、排行榜（飙升/新歌/原创等）、相似歌曲推荐
- **链接解析播放**：粘贴网易云分享链接/`163cn.tv` 短链，自动展开并播放
- **解灰兜底**：VIP/灰歌自动尝试可用音源（`unblock`，音质可能降级）
- **播放记录**：猫娘播放的歌曲自动记入内部播放记录（最近 200 条，仅内部保存）
- **音乐偏好**：面板内手动填写，或让猫娘根据对话与播放记录自主总结后写入
- **LLM 工具（10 个）**：`search_songs` / `play_song` / `play_random_song` /
  `get_lyrics` / `get_hot_search` / `get_toplist` / `get_similar_songs` /
  `resolve_and_play` / `get_music_preferences` / `update_music_preferences`
- **插件入口（6 个）**：`test_api`（连通性自检）/ `show_status`（配置与登录态）/
  `search_and_play`（手动点歌）/ `show_library`（播放记录）/
  `save_preferences`（保存偏好）/ `summarize_preferences`（猫娘总结偏好）
- **桌面播放通道**：`media_allowlist_add` 域名白名单（含 SSRF 防护校验）→
  `media_play_url` 桌面播放器播放
- **Hosted UI 面板**：偏好设置 / 播放记录

---

## 前置条件

1. **部署 NeteaseCloudMusicApiEnhanced（api-enhanced）服务**并保持运行
   （Node 项目，参见其仓库文档），默认地址 `http://127.0.0.1:3000`；
2. 在插件配置 `[netease_music].api_base` 中填入服务地址；
3. （可选）在 `cookie` 中填入网易云 `MUSIC_U=...` 以解锁会员音质与账号能力。

## ⚙️ 配置（plugin.toml 的 `[netease_music]` 节）

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
- "我喜欢什么风格的歌" → `get_music_preferences`

或直接粘贴网易云分享链接/短链（`music.163.com` / `163cn.tv`），自动解析并播放：

- `https://music.163.com/#/song?id=186016` → `resolve_and_play`（入参是链接本身）

插件详情页的 **管理面板** 可查看音乐偏好与猫娘播放记录。

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

本插件采用 [MIT](LICENSE) 许可证。
