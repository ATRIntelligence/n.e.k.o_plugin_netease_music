import {
  ActionButton,
  Button,
  Card,
  DataTable,
  EmptyState,
  Field,
  Page,
  RefreshButton,
  Stack,
  Textarea,
  Toolbar,
} from "@neko/plugin-ui"
import type { HostedAction, PluginSurfaceProps } from "@neko/plugin-ui"
import { useEffect, useState } from "@neko/plugin-ui"

type Song = { name: string; artist: string; played_at?: string; added_at?: string }
type Daily = { date: string; title: string; songs: Song[] }
type Prefs = { text: string; updated_at?: string; updated_by?: string }
type State = { daily?: Daily; played?: Song[]; favorites?: Song[]; preferences?: Prefs }

/**
 * 网易云音乐 — 基础面板：偏好设置 / 今日歌单 / 播放记录 / 本地收藏。
 * 偏好可手动填写（保存按钮），也可由猫娘自主总结（LLM 工具 update_music_preferences）。
 */
export default function Panel(props: PluginSurfaceProps<State>) {
  const { actions, state, t } = props
  const daily = state.daily || { date: "", title: "", songs: [] }
  const played = state.played || []
  const favorites = state.favorites || []
  const preferences = state.preferences || { text: "", updated_at: "", updated_by: "" }

  const [prefText, setPrefText] = useState(preferences.text)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    setPrefText(preferences.text)
  }, [preferences.text])

  const summarize = actions.find(
    (action) => action.id === "summarize_preferences",
  ) as HostedAction | undefined

  const colName = t("panel.col.name", { defaultValue: "歌曲" })
  const colArtist = t("panel.col.artist", { defaultValue: "歌手" })
  const colTime = t("panel.col.time", { defaultValue: "时间" })
  const empty = t("panel.empty", { defaultValue: "暂无记录" })

  const savePreferences = async () => {
    setSaving(true)
    try {
      await props.api.call("save_preferences", { preferences: prefText })
      await props.api.refresh()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Page title={props.plugin.name}>
      <Stack gap={12}>
        <Toolbar>
          <RefreshButton label={t("panel.refresh", { defaultValue: "刷新" })} tone="primary" />
        </Toolbar>

        <Card title={t("panel.preferences", { defaultValue: "偏好设置" })}>
          <Field
            label={t("panel.preferences.label", { defaultValue: "音乐偏好" })}
            help={
              preferences.updated_at
                ? `${t("panel.preferences.updated", { defaultValue: "最近更新" })}: ${preferences.updated_at} · ${preferences.updated_by}`
                : undefined
            }
          >
            <Textarea
              value={prefText}
              placeholder={t("panel.preferences.placeholder", {
                defaultValue: "例如：喜欢日系摇滚和纯音乐，常听 YOASOBI，学习时偏好无人声……",
              })}
              onChange={(value: string) => setPrefText(value)}
            />
          </Field>
          <Toolbar>
            <Button tone="primary" disabled={saving} onClick={savePreferences}>
              {t("panel.preferences.save", { defaultValue: "保存" })}
            </Button>
            {summarize ? (
              <ActionButton
                action={summarize}
                label={t("panel.preferences.summary", { defaultValue: "让猫娘总结" })}
                tone="info"
              />
            ) : null}
          </Toolbar>
        </Card>

        <Card
          title={
            t("panel.daily", { defaultValue: "今日歌单" }) +
            (daily.date ? ` · ${daily.date}` : "")
          }
        >
          {daily.songs.length ? (
            <DataTable
              data={daily.songs}
              rowKey="name"
              columns={[
                { key: "name", label: colName },
                { key: "artist", label: colArtist },
              ]}
            />
          ) : (
            <EmptyState title={empty} />
          )}
        </Card>

        <Card title={t("panel.played", { defaultValue: "播放记录" })}>
          {played.length ? (
            <DataTable
              data={played}
              rowKey="played_at"
              maxRows={20}
              columns={[
                { key: "name", label: colName },
                { key: "artist", label: colArtist },
                { key: "played_at", label: colTime },
              ]}
            />
          ) : (
            <EmptyState title={empty} />
          )}
        </Card>

        <Card title={t("panel.favorites", { defaultValue: "本地收藏" })}>
          {favorites.length ? (
            <DataTable
              data={favorites}
              rowKey="name"
              columns={[
                { key: "name", label: colName },
                { key: "artist", label: colArtist },
                { key: "added_at", label: colTime },
              ]}
            />
          ) : (
            <EmptyState title={empty} />
          )}
        </Card>
      </Stack>
    </Page>
  )
}
