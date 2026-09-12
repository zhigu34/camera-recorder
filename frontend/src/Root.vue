<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import {
  Bell, Calendar, Camera, CircleCheckFilled, DataAnalysis, Expand, Files, Fold,
  Monitor, Moon, Setting, Sunny, UploadFilled, VideoCamera, VideoPlay, WarningFilled,
} from '@element-plus/icons-vue'

import CamerasWorkspace from './CamerasWorkspace.vue'
import DashboardView from './DashboardView.vue'
import EventCenterView from './EventCenterView.vue'
import HealthView from './HealthView.vue'
import PlaybackMetricsPanel from './PlaybackMetricsPanel.vue'
import PlaybackTelemetryBridge from './PlaybackTelemetryBridge.vue'
import PreviewView from './PreviewView.vue'
import RecordingBrowserView from './RecordingBrowserView.vue'
import RecordingCalendarLegend from './RecordingCalendarLegend.vue'
import RecordingManagementView from './RecordingManagementView.vue'
import RecordingScheduleView from './RecordingScheduleView.vue'
import RecordingTimelineLegend from './RecordingTimelineLegend.vue'
import SystemSettingsWorkspace from './SystemSettingsWorkspace.vue'
import UploadManagementView from './UploadManagementView.vue'

interface NavEntry {
  key: string
  label: string
  description: string
  kind: 'dashboard' | 'route'
  target: string
  group: 'core' | 'ops' | 'settings'
  icon: object
}
interface ShellStatus {
  ffmpeg?: { setts_available?: boolean }
  recorders?: Array<{ camera_id: number; state: string }>
  recording_schedule?: { cameras?: Array<{ camera_id: number }> }
  upload?: { enabled: boolean; configured: boolean; active: boolean }
  storage?: { used_percent: number; state: 'healthy' | 'warning' | 'critical' }
}
type ThemeMode = 'light' | 'dark'

const navEntries: NavEntry[] = [
  { key: 'dashboard', label: '总览', description: '运行概览与异常状态', kind: 'dashboard', target: '/', group: 'core', icon: markRaw(DataAnalysis) },
  { key: 'preview', label: '实时监控', description: '实时画面与码流状态', kind: 'route', target: '/preview', group: 'core', icon: markRaw(VideoCamera) },
  { key: 'playback', label: '录像回放', description: '检索、时间轴与兼容回放', kind: 'route', target: '/recordings/browser', group: 'core', icon: markRaw(VideoPlay) },
  { key: 'cameras', label: '摄像头', description: '设备、码流与录像配置', kind: 'route', target: '/cameras', group: 'core', icon: markRaw(Camera) },
  { key: 'schedule', label: '录制计划', description: '自动录像与时间窗口', kind: 'route', target: '/recording-schedules', group: 'core', icon: markRaw(Calendar) },
  { key: 'health', label: '系统健康', description: '录像服务、存储与稳定性', kind: 'route', target: '/health-center', group: 'ops', icon: markRaw(Monitor) },
  { key: 'recordings', label: '录像管理', description: '录像资产与归档状态', kind: 'route', target: '/recordings/manage', group: 'ops', icon: markRaw(Files) },
  { key: 'uploads', label: '上传管理', description: 'OpenList 归档任务与传输', kind: 'route', target: '/uploads', group: 'ops', icon: markRaw(UploadFilled) },
  { key: 'events', label: '事件中心', description: '异常、告警与运行事件', kind: 'route', target: '/events', group: 'ops', icon: markRaw(Bell) },
  { key: 'settings', label: '系统设置', description: '录像、存储与通知配置', kind: 'route', target: '/settings', group: 'settings', icon: markRaw(Setting) },
]
const entryMap = new Map(navEntries.map((item) => [item.key, item]))

const collapsed = ref(localStorage.getItem('nvr-sidebar-collapsed') === '1')
const themeMode = ref<ThemeMode>(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark')
const activeKey = ref('dashboard')
const renderKey = ref('dashboard')
const shellStatus = ref<ShellStatus | null>(null)
const statusError = ref(false)
let statusTimer: number | null = null

const activeEntry = computed(() => entryMap.get(activeKey.value) || entryMap.get('dashboard')!)
const coreEntries = computed(() => navEntries.filter((item) => item.group === 'core'))
const opsEntries = computed(() => navEntries.filter((item) => item.group === 'ops'))
const settingsEntry = computed(() => navEntries.find((item) => item.group === 'settings')!)
const recordingCount = computed(() => (shellStatus.value?.recorders || []).filter((item) => item.state === 'RECORDING').length)
const cameraCount = computed(() => shellStatus.value?.recording_schedule?.cameras?.length ?? 0)
const storageState = computed(() => shellStatus.value?.storage?.state || 'healthy')
const systemHealthy = computed(() => Boolean(
  shellStatus.value && !statusError.value && shellStatus.value.ffmpeg?.setts_available !== false && storageState.value !== 'critical',
))

function locationKey() {
  const path = window.location.pathname
  if (path === '/alerts') return 'settings'
  if (path === '/cameras/batch') return 'cameras'
  if (path === '/') {
    const view = new URLSearchParams(window.location.search).get('view')
    return view && entryMap.has(view) ? view : 'dashboard'
  }
  return navEntries.find((item) => item.kind === 'route' && item.target === path)?.key || 'dashboard'
}
function urlFor(entry: NavEntry) {
  return entry.kind === 'dashboard' ? '/' : entry.target
}
function showEntry(entry: NavEntry, historyMode: 'push' | 'replace' | 'none' = 'push') {
  activeKey.value = entry.key
  renderKey.value = entry.key
  const url = urlFor(entry)
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`
  if (historyMode === 'push' && current !== url) window.history.pushState({}, '', url)
  else if (historyMode === 'replace' && window.location.pathname !== url) window.history.replaceState({}, '', url)
}
function navigate(key: string) {
  const entry = entryMap.get(key)
  if (entry) showEntry(entry)
}
function openPlaybackCompatibility() {
  navigate('playback')
  window.setTimeout(() => {
    document.getElementById('playback-compatibility')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 80)
}
function toggleSidebar() {
  collapsed.value = !collapsed.value
  localStorage.setItem('nvr-sidebar-collapsed', collapsed.value ? '1' : '0')
}
function setTheme(mode: ThemeMode) {
  themeMode.value = mode
  document.documentElement.dataset.theme = mode
  document.documentElement.classList.toggle('dark', mode === 'dark')
  localStorage.setItem('nvr-theme', mode)
}
function toggleTheme() {
  setTheme(themeMode.value === 'dark' ? 'light' : 'dark')
}
async function loadShellStatus() {
  try {
    shellStatus.value = (await axios.get<ShellStatus>('/api/system/status')).data
    statusError.value = false
  } catch {
    statusError.value = true
  }
}
function handlePopState() {
  showEntry(entryMap.get(locationKey()) || entryMap.get('dashboard')!, 'none')
}

onMounted(() => {
  const initialKey = locationKey()
  const legacyAlerts = window.location.pathname === '/alerts'
  showEntry(entryMap.get(initialKey) || entryMap.get('dashboard')!, 'replace')
  if (legacyAlerts) window.history.replaceState({}, '', '/settings?section=alerts')
  void loadShellStatus()
  statusTimer = window.setInterval(loadShellStatus, 10000)
  window.addEventListener('popstate', handlePopState)
})
onBeforeUnmount(() => {
  if (statusTimer !== null) window.clearInterval(statusTimer)
  window.removeEventListener('popstate', handlePopState)
})
</script>

<template>
  <div class="nvr-shell" :class="{ 'sidebar-collapsed': collapsed }">
    <aside class="nvr-sidebar">
      <div class="brand-row">
        <div class="brand-mark"><VideoCamera /></div>
        <div v-if="!collapsed" class="brand-copy"><strong>Camera Recorder</strong><span>NVR Console</span></div>
      </div>
      <nav class="nav-scroll">
        <div class="nav-group">
          <div v-if="!collapsed" class="nav-caption">监控</div>
          <button v-for="item in coreEntries" :key="item.key" class="nav-item" :class="{ active: activeKey === item.key }" :title="collapsed ? item.label : undefined" @click="navigate(item.key)">
            <component :is="item.icon" class="nav-icon" /><span v-if="!collapsed">{{ item.label }}</span>
          </button>
        </div>
        <div class="nav-group">
          <div v-if="!collapsed" class="nav-caption">运维</div>
          <button v-for="item in opsEntries" :key="item.key" class="nav-item" :class="{ active: activeKey === item.key }" :title="collapsed ? item.label : undefined" @click="navigate(item.key)">
            <component :is="item.icon" class="nav-icon" /><span v-if="!collapsed">{{ item.label }}</span>
          </button>
        </div>
      </nav>
      <div class="sidebar-bottom">
        <button class="nav-item" :class="{ active: activeKey === settingsEntry.key }" :title="collapsed ? settingsEntry.label : undefined" @click="navigate(settingsEntry.key)">
          <component :is="settingsEntry.icon" class="nav-icon" /><span v-if="!collapsed">{{ settingsEntry.label }}</span>
        </button>
        <button class="collapse-button" :title="collapsed ? '展开侧栏' : '收起侧栏'" @click="toggleSidebar"><Expand v-if="collapsed" /><Fold v-else /><span v-if="!collapsed">收起菜单</span></button>
      </div>
    </aside>

    <section class="nvr-workspace">
      <header class="nvr-topbar">
        <div class="topbar-title">
          <button class="top-collapse" :title="collapsed ? '展开侧栏' : '收起侧栏'" @click="toggleSidebar"><Expand v-if="collapsed" /><Fold v-else /></button>
          <div><strong>{{ activeEntry.label }}</strong><span>{{ activeEntry.description }}</span></div>
        </div>
        <div class="topbar-actions">
          <span class="build-label">v0.9.1</span>
          <button class="theme-toggle" :title="themeMode === 'dark' ? '切换浅色模式' : '切换深色模式'" @click="toggleTheme">
            <Sunny v-if="themeMode === 'dark'" /><Moon v-else />
          </button>
          <div class="system-pill" :class="{ healthy: systemHealthy, danger: !systemHealthy }"><CircleCheckFilled v-if="systemHealthy" /><WarningFilled v-else /><span>{{ statusError ? '状态不可用' : systemHealthy ? '系统正常' : '需要关注' }}</span></div>
        </div>
      </header>

      <main class="nvr-workspace-content">
        <DashboardView v-if="renderKey === 'dashboard'" />
        <CamerasWorkspace v-else-if="renderKey === 'cameras'" @open-preview="navigate('preview')" />
        <RecordingManagementView v-else-if="renderKey === 'recordings'" @open-playback="navigate('playback')" @open-uploads="navigate('uploads')" />
        <UploadManagementView v-else-if="renderKey === 'uploads'" @open-settings="navigate('settings')" @open-recordings="navigate('recordings')" />
        <EventCenterView v-else-if="renderKey === 'events'" @open-cameras="navigate('cameras')" @open-recordings="navigate('recordings')" @open-uploads="navigate('uploads')" @open-health="navigate('health')" />
        <PreviewView v-else-if="renderKey === 'preview'" />
        <template v-else-if="renderKey === 'playback'"><RecordingBrowserView /><PlaybackTelemetryBridge /><PlaybackMetricsPanel /><RecordingCalendarLegend /><RecordingTimelineLegend /></template>
        <RecordingScheduleView v-else-if="renderKey === 'schedule'" />
        <template v-else-if="renderKey === 'health'"><HealthView /><PlaybackMetricsPanel compact @open-playback="openPlaybackCompatibility" /></template>
        <SystemSettingsWorkspace v-else-if="renderKey === 'settings'" @open-events="navigate('events')" />
      </main>

      <footer class="nvr-statusbar">
        <div class="status-left"><span class="status-dot" :class="{ ok: systemHealthy, bad: !systemHealthy }"></span><span>{{ systemHealthy ? '运行正常' : '状态异常' }}</span></div>
        <div class="status-items">
          <span><b>{{ recordingCount }}/{{ cameraCount || '-' }}</b> 录像中</span>
          <span>磁盘 <b :class="`storage-${storageState}`">{{ shellStatus?.storage?.used_percent ?? '-' }}%</b></span>
          <span>上传 <b>{{ shellStatus?.upload?.enabled ? shellStatus?.upload?.configured ? '正常' : '未配置' : '关闭' }}</b></span>
          <span>FFmpeg <b>{{ shellStatus?.ffmpeg?.setts_available ? '正常' : '异常' }}</b></span>
        </div>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.nvr-shell{min-height:100vh;display:grid;grid-template-columns:var(--nvr-sidebar-width) minmax(0,1fr);background:var(--nvr-bg);transition:grid-template-columns .18s ease,background-color .18s ease}.nvr-shell.sidebar-collapsed{grid-template-columns:var(--nvr-sidebar-collapsed) minmax(0,1fr)}
.nvr-sidebar{position:sticky;top:0;height:100vh;z-index:30;display:flex;flex-direction:column;min-width:0;background:var(--nvr-sidebar);border-right:1px solid var(--nvr-border);transition:background-color .18s ease,border-color .18s ease}
.brand-row{height:60px;display:flex;align-items:center;gap:10px;padding:0 14px;overflow:hidden}.brand-mark{flex:0 0 30px;width:30px;height:30px;display:grid;place-items:center;color:#fff;border-radius:8px;background:var(--nvr-blue);box-shadow:0 5px 16px color-mix(in srgb,var(--nvr-blue) 20%,transparent)}.brand-mark :deep(svg){width:16px}.brand-copy{min-width:0;display:flex;flex-direction:column;line-height:1.2;white-space:nowrap}.brand-copy strong{font-size:13px;font-weight:650;letter-spacing:-.015em}.brand-copy span{margin-top:3px;color:var(--nvr-subtle);font-size:9px;font-weight:600;letter-spacing:.11em;text-transform:uppercase}
.nav-scroll{flex:1;overflow:auto;padding:12px 8px}.nav-group+.nav-group{margin-top:20px}.nav-caption{padding:0 10px 6px;color:var(--nvr-subtle);font-size:9px;font-weight:650;letter-spacing:.11em}.nav-item,.collapse-button,.top-collapse,.theme-toggle{appearance:none;border:0;color:var(--nvr-nav-text);background:transparent;cursor:pointer}.nav-item{position:relative;width:100%;height:38px;display:flex;align-items:center;gap:10px;padding:0 10px;margin:1px 0;border-radius:8px;font-size:12px;font-weight:520;text-align:left;white-space:nowrap;overflow:hidden;transition:background-color .14s ease,color .14s ease,box-shadow .14s ease}.nav-item:hover{color:var(--nvr-nav-hover-text);background:var(--nvr-nav-hover)}.nav-item.active{color:var(--nvr-nav-active-text);background:var(--nvr-nav-active);box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--nvr-blue) 10%,transparent)}.nav-icon{flex:0 0 16px;width:16px;height:16px;opacity:.9}.nav-item.active .nav-icon{opacity:1}.sidebar-collapsed .nav-item{justify-content:center;padding:0}.sidebar-bottom{padding:8px;border-top:1px solid var(--nvr-border)}.collapse-button{width:100%;height:32px;display:flex;align-items:center;justify-content:center;gap:7px;color:var(--nvr-subtle);font-size:10px;border-radius:7px}.collapse-button:hover{color:var(--nvr-text-soft);background:var(--nvr-control-hover)}.collapse-button :deep(svg){width:14px}
.nvr-workspace{min-width:0;min-height:100vh;display:grid;grid-template-rows:60px minmax(0,1fr) 28px}.nvr-topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 18px;background:var(--nvr-topbar);backdrop-filter:blur(18px) saturate(1.1);border-bottom:1px solid var(--nvr-border);transition:background-color .18s ease,border-color .18s ease}.topbar-title{display:flex;align-items:center;gap:10px;min-width:0}.topbar-title>div{display:flex;flex-direction:column;min-width:0}.topbar-title strong{font-size:14px;font-weight:650;letter-spacing:-.015em;line-height:1.15}.topbar-title span{margin-top:3px;color:var(--nvr-subtle);font-size:10px;line-height:1.2}.top-collapse,.theme-toggle{width:30px;height:30px;display:grid;place-items:center;border-radius:7px;transition:background-color .14s ease,color .14s ease}.top-collapse:hover,.theme-toggle:hover{color:var(--nvr-text);background:var(--nvr-control-hover)}.top-collapse :deep(svg),.theme-toggle :deep(svg){width:15px}.topbar-actions{display:flex;align-items:center;gap:7px}.build-label{color:var(--nvr-subtle);font-size:9px;font-variant-numeric:tabular-nums}.theme-toggle{border:1px solid var(--nvr-border);color:var(--nvr-muted);background:var(--nvr-pill-bg)}.system-pill{height:30px;display:flex;align-items:center;gap:6px;padding:0 9px;border:1px solid var(--nvr-border);border-radius:8px;font-size:10px;font-weight:560;background:var(--nvr-pill-bg)}.system-pill :deep(svg){width:11px}.system-pill.healthy{color:var(--nvr-green)}.system-pill.danger{color:var(--nvr-red)}
.nvr-workspace-content{min-width:0;overflow-x:hidden;background:var(--nvr-bg);transition:background-color .18s ease}
.nvr-workspace-content :deep(.dashboard-head h1),.nvr-workspace-content :deep(.page-heading h1),.nvr-workspace-content :deep(.page-head>div>h2),.nvr-workspace-content :deep(.wall-header>div>h2),.nvr-workspace-content :deep(.page>.topbar>div>h2){display:none}
.nvr-workspace-content :deep(.dashboard-head>div:first-child>.eyebrow),.nvr-workspace-content :deep(.dashboard-head>div:first-child>p),.nvr-workspace-content :deep(.page-heading>div:first-child>p),.nvr-workspace-content :deep(.page-head>div:first-child>p),.nvr-workspace-content :deep(.wall-header>div:first-child>.eyebrow),.nvr-workspace-content :deep(.wall-header>div:first-child>p),.nvr-workspace-content :deep(.page>.topbar>div:first-child>.hint){display:none}
.nvr-statusbar{position:sticky;bottom:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:14px;padding:0 12px;color:var(--nvr-subtle);background:var(--nvr-statusbar);border-top:1px solid var(--nvr-border);font-size:9px;transition:background-color .18s ease,border-color .18s ease}.status-left,.status-items{display:flex;align-items:center;gap:13px;white-space:nowrap}.status-dot{width:5px;height:5px;border-radius:50%}.status-dot.ok{background:var(--nvr-green)}.status-dot.bad{background:var(--nvr-red)}.status-items b{color:var(--nvr-text-soft);font-weight:600;font-variant-numeric:tabular-nums}.status-items .storage-warning{color:var(--nvr-yellow)}.status-items .storage-critical{color:var(--nvr-red)}
@media(max-width:900px){.nvr-shell{grid-template-columns:var(--nvr-sidebar-collapsed) minmax(0,1fr)}.nvr-sidebar{width:var(--nvr-sidebar-collapsed)}.brand-copy,.nav-caption,.nav-item span,.collapse-button span{display:none!important}.nav-item{justify-content:center;padding:0}.status-items span:nth-child(3),.status-items span:nth-child(4){display:none}}
@media(max-width:620px){.nvr-shell{grid-template-columns:0 minmax(0,1fr)}.nvr-sidebar{transform:translateX(-68px);pointer-events:none}.nvr-shell:not(.sidebar-collapsed){grid-template-columns:var(--nvr-sidebar-width) minmax(0,1fr)}.nvr-shell:not(.sidebar-collapsed) .nvr-sidebar{width:var(--nvr-sidebar-width);transform:none;pointer-events:auto}.nvr-shell:not(.sidebar-collapsed) .brand-copy,.nvr-shell:not(.sidebar-collapsed) .nav-caption,.nvr-shell:not(.sidebar-collapsed) .nav-item span,.nvr-shell:not(.sidebar-collapsed) .collapse-button span{display:initial!important}.nvr-shell:not(.sidebar-collapsed) .nav-item{justify-content:flex-start;padding:0 10px}.nvr-statusbar{overflow:hidden}.status-items span:nth-child(2){display:none}.system-pill span,.build-label{display:none}.system-pill{padding:0 8px}.topbar-actions{gap:6px}.topbar-title span{display:none}}
</style>