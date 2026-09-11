<script setup lang="ts">
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import {
  Bell, Calendar, Camera, CircleCheckFilled, DataAnalysis, Expand, Files, Fold,
  Monitor, Plus, Setting, UploadFilled, VideoCamera, VideoPlay, WarningFilled,
} from '@element-plus/icons-vue'

import App from './App.vue'
import BatchCamerasView from './BatchCamerasView.vue'
import CamerasViewV2 from './CamerasViewV2.vue'
import DashboardView from './DashboardView.vue'
import HealthView from './HealthView.vue'
import PlaybackMetricsPanel from './PlaybackMetricsPanel.vue'
import PlaybackTelemetryBridge from './PlaybackTelemetryBridge.vue'
import PreviewView from './PreviewView.vue'
import RecordingBrowserViewV3 from './RecordingBrowserViewV3.vue'
import RecordingCalendarLegend from './RecordingCalendarLegend.vue'
import RecordingScheduleView from './RecordingScheduleView.vue'
import RecordingTimelineLegend from './RecordingTimelineLegend.vue'
import SystemSettingsView from './SystemSettingsView.vue'

interface NavEntry {
  key: string
  label: string
  kind: 'dashboard' | 'legacy' | 'route'
  target: string
  group: 'core' | 'ops' | 'settings'
  icon: object
}
interface ShellStatus {
  ffmpeg?: { setts_available?: boolean }
  recorders?: Array<{ camera_id: number; state: string }>
  upload?: { enabled: boolean; configured: boolean; active: boolean }
  storage?: { used_percent: number; state: 'healthy' | 'warning' | 'critical' }
}

const navEntries: NavEntry[] = [
  { key: 'dashboard', label: '总览', kind: 'dashboard', target: '/', group: 'core', icon: markRaw(DataAnalysis) },
  { key: 'preview', label: '实时监控', kind: 'route', target: '/preview', group: 'core', icon: markRaw(VideoCamera) },
  { key: 'playback', label: '录像回放', kind: 'route', target: '/recordings/browser', group: 'core', icon: markRaw(VideoPlay) },
  { key: 'cameras', label: '摄像头', kind: 'route', target: '/cameras', group: 'core', icon: markRaw(Camera) },
  { key: 'schedule', label: '录制计划', kind: 'route', target: '/recording-schedules', group: 'core', icon: markRaw(Calendar) },
  { key: 'health', label: '系统健康', kind: 'route', target: '/health-center', group: 'ops', icon: markRaw(Monitor) },
  { key: 'recordings', label: '录像文件', kind: 'legacy', target: 'recordings', group: 'ops', icon: markRaw(Files) },
  { key: 'uploads', label: '上传管理', kind: 'legacy', target: 'uploads', group: 'ops', icon: markRaw(UploadFilled) },
  { key: 'events', label: '事件中心', kind: 'legacy', target: 'events', group: 'ops', icon: markRaw(Bell) },
  { key: 'alerts', label: '告警设置', kind: 'legacy', target: 'alerts', group: 'ops', icon: markRaw(WarningFilled) },
  { key: 'batch', label: '批量添加', kind: 'route', target: '/cameras/batch', group: 'ops', icon: markRaw(Plus) },
  { key: 'settings', label: '系统设置', kind: 'route', target: '/settings', group: 'settings', icon: markRaw(Setting) },
]
const entryMap = new Map(navEntries.map((item) => [item.key, item]))
const legacyLabels: Record<string, string> = {
  recordings: '录像文件', uploads: '115 上传', events: '事件中心', alerts: '告警设置',
}

const collapsed = ref(localStorage.getItem('nvr-sidebar-collapsed') === '1')
const activeKey = ref('dashboard')
const renderKey = ref('dashboard')
const shellStatus = ref<ShellStatus | null>(null)
const cameraCount = ref(0)
const statusError = ref(false)
let statusTimer: number | null = null

const activeEntry = computed(() => entryMap.get(activeKey.value) || entryMap.get('dashboard')!)
const coreEntries = computed(() => navEntries.filter((item) => item.group === 'core'))
const opsEntries = computed(() => navEntries.filter((item) => item.group === 'ops'))
const settingsEntry = computed(() => navEntries.find((item) => item.group === 'settings')!)
const isLegacy = computed(() => activeEntry.value.kind === 'legacy')
const recordingCount = computed(() => (shellStatus.value?.recorders || []).filter((item) => item.state === 'RECORDING').length)
const storageState = computed(() => shellStatus.value?.storage?.state || 'healthy')
const systemHealthy = computed(() => Boolean(
  shellStatus.value && !statusError.value && shellStatus.value.ffmpeg?.setts_available !== false && storageState.value !== 'critical',
))

function locationKey() {
  const path = window.location.pathname
  if (path === '/') {
    const view = new URLSearchParams(window.location.search).get('view')
    return view && entryMap.has(view) ? view : 'dashboard'
  }
  return navEntries.find((item) => item.kind === 'route' && item.target === path)?.key || 'dashboard'
}
function urlFor(entry: NavEntry) {
  if (entry.kind === 'dashboard') return '/'
  if (entry.kind === 'legacy') return `/?view=${entry.target}`
  return entry.target
}
async function activateLegacySection(section: string) {
  await nextTick()
  window.requestAnimationFrame(() => {
    const label = legacyLabels[section]
    if (!label) return
    const items = Array.from(document.querySelectorAll<HTMLElement>('.legacy-host .sidebar .el-menu-item'))
    items.find((item) => item.textContent?.trim() === label)?.click()
  })
}
async function showEntry(entry: NavEntry, historyMode: 'push' | 'replace' | 'none' = 'push') {
  activeKey.value = entry.key
  renderKey.value = entry.key
  const url = urlFor(entry)
  if (historyMode === 'push' && `${window.location.pathname}${window.location.search}` !== url) window.history.pushState({}, '', url)
  else if (historyMode === 'replace') window.history.replaceState({}, '', url)
  if (entry.kind === 'legacy') await activateLegacySection(entry.target)
}
function navigate(key: string) {
  const entry = entryMap.get(key)
  if (entry) void showEntry(entry)
}
function toggleSidebar() {
  collapsed.value = !collapsed.value
  localStorage.setItem('nvr-sidebar-collapsed', collapsed.value ? '1' : '0')
}
async function loadShellStatus() {
  try {
    const [statusRes, cameraRes] = await Promise.all([
      axios.get<ShellStatus>('/api/system/status'), axios.get<Array<{ id: number }>>('/api/cameras'),
    ])
    shellStatus.value = statusRes.data
    cameraCount.value = cameraRes.data.length
    statusError.value = false
  } catch {
    statusError.value = true
  }
}
function handlePopState() {
  void showEntry(entryMap.get(locationKey()) || entryMap.get('dashboard')!, 'none')
}

onMounted(() => {
  void showEntry(entryMap.get(locationKey()) || entryMap.get('dashboard')!, 'replace')
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
          <div><strong>{{ activeEntry.label }}</strong><span>Camera Recorder · v0.9.0</span></div>
        </div>
        <div class="system-pill" :class="{ healthy: systemHealthy, danger: !systemHealthy }"><CircleCheckFilled v-if="systemHealthy" /><WarningFilled v-else /><span>{{ statusError ? '状态不可用' : systemHealthy ? '系统正常' : '需要关注' }}</span></div>
      </header>

      <main class="nvr-workspace-content">
        <DashboardView v-if="renderKey === 'dashboard'" />
        <CamerasViewV2 v-else-if="renderKey === 'cameras'" @open-batch="navigate('batch')" @open-preview="navigate('preview')" />
        <div v-else-if="isLegacy" class="legacy-host"><App /></div>
        <PreviewView v-else-if="renderKey === 'preview'" />
        <template v-else-if="renderKey === 'playback'"><RecordingBrowserViewV3 /><PlaybackTelemetryBridge /><RecordingCalendarLegend /><RecordingTimelineLegend /></template>
        <RecordingScheduleView v-else-if="renderKey === 'schedule'" />
        <template v-else-if="renderKey === 'health'"><HealthView /><PlaybackMetricsPanel /></template>
        <BatchCamerasView v-else-if="renderKey === 'batch'" />
        <SystemSettingsView v-else-if="renderKey === 'settings'" />
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
.nvr-shell{min-height:100vh;display:grid;grid-template-columns:var(--nvr-sidebar-width) minmax(0,1fr);background:var(--nvr-bg);transition:grid-template-columns .18s ease}.nvr-shell.sidebar-collapsed{grid-template-columns:var(--nvr-sidebar-collapsed) minmax(0,1fr)}
.nvr-sidebar{position:sticky;top:0;height:100vh;z-index:30;display:flex;flex-direction:column;min-width:0;background:var(--nvr-sidebar);border-right:1px solid var(--nvr-border)}
.brand-row{height:68px;display:flex;align-items:center;gap:11px;padding:0 16px;border-bottom:1px solid var(--nvr-border);overflow:hidden}.brand-mark{flex:0 0 36px;width:36px;height:36px;display:grid;place-items:center;color:white;border-radius:10px;background:linear-gradient(145deg,#397cf0,#6c9fff);box-shadow:0 6px 20px rgba(76,141,255,.22)}.brand-mark :deep(svg){width:19px}.brand-copy{min-width:0;display:flex;flex-direction:column;line-height:1.2;white-space:nowrap}.brand-copy strong{font-size:14px}.brand-copy span{margin-top:4px;color:var(--nvr-muted);font-size:10px;letter-spacing:.12em;text-transform:uppercase}
.nav-scroll{flex:1;overflow:auto;padding:14px 10px}.nav-group+.nav-group{margin-top:22px}.nav-caption{padding:0 10px 7px;color:#607085;font-size:10px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}.nav-item,.collapse-button,.top-collapse{appearance:none;border:0;color:#9aa7b7;background:transparent;cursor:pointer}.nav-item{position:relative;width:100%;height:42px;display:flex;align-items:center;gap:11px;padding:0 11px;margin:2px 0;border-radius:8px;font-size:13px;text-align:left;white-space:nowrap;overflow:hidden;transition:.15s}.nav-item:hover{color:#d9e2ec;background:rgba(255,255,255,.045)}.nav-item.active{color:#f2f6fa;background:rgba(76,141,255,.13)}.nav-item.active:before{content:'';position:absolute;left:0;width:2px;height:20px;border-radius:0 2px 2px 0;background:var(--nvr-blue)}.nav-icon{flex:0 0 18px;width:18px;height:18px}.sidebar-collapsed .nav-item{justify-content:center;padding:0}.sidebar-bottom{padding:10px;border-top:1px solid var(--nvr-border)}.collapse-button{width:100%;height:36px;display:flex;align-items:center;justify-content:center;gap:8px;color:#66758a;font-size:12px}.collapse-button:hover{color:var(--nvr-text)}.collapse-button :deep(svg){width:16px}
.nvr-workspace{min-width:0;min-height:100vh;display:grid;grid-template-rows:68px minmax(0,1fr) 30px}.nvr-topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 20px;background:rgba(11,15,20,.88);backdrop-filter:blur(16px);border-bottom:1px solid var(--nvr-border)}.topbar-title{display:flex;align-items:center;gap:10px;min-width:0}.topbar-title>div{display:flex;flex-direction:column;min-width:0}.topbar-title strong{font-size:15px;font-weight:650}.topbar-title span{margin-top:3px;color:#66758a;font-size:10px}.top-collapse{width:32px;height:32px;display:grid;place-items:center;border-radius:7px}.top-collapse:hover{color:var(--nvr-text);background:rgba(255,255,255,.05)}.top-collapse :deep(svg){width:16px}.system-pill{display:flex;align-items:center;gap:7px;padding:6px 10px;border:1px solid var(--nvr-border);border-radius:999px;font-size:11px;background:rgba(255,255,255,.025)}.system-pill :deep(svg){width:13px}.system-pill.healthy{color:var(--nvr-green)}.system-pill.danger{color:var(--nvr-red)}
.nvr-workspace-content{min-width:0;overflow-x:hidden;background:var(--nvr-bg)}
.nvr-workspace-content :deep(.dashboard-head h1),.nvr-workspace-content :deep(.page-heading h1),.nvr-workspace-content :deep(.page-head>div>h2),.nvr-workspace-content :deep(.wall-header>div>h2),.nvr-workspace-content :deep(.page>.topbar>div>h2){display:none}
.nvr-workspace-content :deep(.dashboard-head>div:first-child>.eyebrow),.nvr-workspace-content :deep(.dashboard-head>div:first-child>p),.nvr-workspace-content :deep(.page-heading>div:first-child>p),.nvr-workspace-content :deep(.page-head>div:first-child>p),.nvr-workspace-content :deep(.wall-header>div:first-child>.eyebrow),.nvr-workspace-content :deep(.wall-header>div:first-child>p),.nvr-workspace-content :deep(.page>.topbar>div:first-child>.hint){display:none}
.nvr-statusbar{position:sticky;bottom:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:14px;padding:0 14px;color:#718095;background:#0d1218;border-top:1px solid var(--nvr-border);font-size:10px}.status-left,.status-items{display:flex;align-items:center;gap:14px;white-space:nowrap}.status-dot{width:6px;height:6px;border-radius:50%}.status-dot.ok{background:var(--nvr-green);box-shadow:0 0 0 3px rgba(46,204,138,.08)}.status-dot.bad{background:var(--nvr-red);box-shadow:0 0 0 3px rgba(240,93,94,.08)}.status-items b{color:#aeb9c6;font-weight:600}.status-items .storage-warning{color:var(--nvr-yellow)}.status-items .storage-critical{color:var(--nvr-red)}
@media(max-width:900px){.nvr-shell{grid-template-columns:var(--nvr-sidebar-collapsed) minmax(0,1fr)}.nvr-sidebar{width:var(--nvr-sidebar-collapsed)}.brand-copy,.nav-caption,.nav-item span,.collapse-button span{display:none!important}.nav-item{justify-content:center;padding:0}.status-items span:nth-child(3),.status-items span:nth-child(4){display:none}}
@media(max-width:620px){.nvr-shell{grid-template-columns:0 minmax(0,1fr)}.nvr-sidebar{transform:translateX(-68px);pointer-events:none}.nvr-shell:not(.sidebar-collapsed){grid-template-columns:var(--nvr-sidebar-width) minmax(0,1fr)}.nvr-shell:not(.sidebar-collapsed) .nvr-sidebar{width:var(--nvr-sidebar-width);transform:none;pointer-events:auto}.nvr-shell:not(.sidebar-collapsed) .brand-copy,.nvr-shell:not(.sidebar-collapsed) .nav-caption,.nvr-shell:not(.sidebar-collapsed) .nav-item span,.nvr-shell:not(.sidebar-collapsed) .collapse-button span{display:initial!important}.nvr-shell:not(.sidebar-collapsed) .nav-item{justify-content:flex-start;padding:0 11px}.nvr-statusbar{overflow:hidden}.status-items span:nth-child(2){display:none}}
</style>