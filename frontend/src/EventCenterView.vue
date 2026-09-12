<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Refresh, Search, WarningFilled } from '@element-plus/icons-vue'
import { useCameraStore } from './stores/cameras'

interface EventItem {
  id: number
  camera_id?: number | null
  recording_id?: number | null
  level: string
  category: string
  code: string
  message: string
  metadata_json?: string | null
  created_at: string
}
type SocketState = 'connecting' | 'connected' | 'disconnected'
type CameraFilter = number | 'all' | 'affected'

const route = useRoute()
const router = useRouter()
const cameraStore = useCameraStore()
const { cameras } = storeToRefs(cameraStore)
const events = ref<EventItem[]>([])
const loading = ref(false)
const keyword = ref('')
const levelFilter = ref('all')
const categoryFilter = ref('all')
const cameraFilter = ref<CameraFilter>('all')
const detailVisible = ref(false)
const selectedEvent = ref<EventItem | null>(null)
const socketState = ref<SocketState>('disconnected')
let eventCursor: number | null = null
let reconnectTimer: number | null = null
let socket: WebSocket | null = null
let mounted = false

const categories = computed(() => Array.from(new Set(events.value.map((item) => item.category).filter(Boolean))).sort())
const levelOptions = computed(() => Array.from(new Set(events.value.map((item) => item.level).filter(Boolean))).sort())
const recent24h = computed(() => {
  const threshold = Date.now() - 24 * 60 * 60 * 1000
  return events.value.filter((item) => {
    const parsed = Date.parse(item.created_at.replace(' ', 'T'))
    return Number.isFinite(parsed) && parsed >= threshold
  }).length
})
const warningCount = computed(() => events.value.filter((item) => ['warning', 'warn'].includes(item.level.toLowerCase())).length)
const errorCount = computed(() => events.value.filter((item) => ['error', 'critical', 'fatal'].includes(item.level.toLowerCase())).length)
const affectedCameras = computed(() => new Set(events.value.map((item) => item.camera_id).filter((id): id is number => typeof id === 'number')).size)
const liveLabel = computed(() => socketState.value === 'connected' ? 'WebSocket 实时事件流' : socketState.value === 'connecting' ? '实时事件流连接中' : '实时事件流重连中')

const filteredEvents = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  return events.value.filter((item) => {
    const level = item.level.toLowerCase()
    if (levelFilter.value === 'warnings' && !['warning', 'warn'].includes(level)) return false
    if (levelFilter.value === 'problems' && !['error', 'critical', 'fatal'].includes(level)) return false
    if (!['all', 'warnings', 'problems'].includes(levelFilter.value) && item.level !== levelFilter.value) return false
    if (categoryFilter.value !== 'all' && item.category !== categoryFilter.value) return false
    if (cameraFilter.value === 'affected' && typeof item.camera_id !== 'number') return false
    if (typeof cameraFilter.value === 'number' && item.camera_id !== cameraFilter.value) return false
    if (!needle) return true
    const camera = cameraName(item.camera_id)
    return [item.message, item.code, item.category, item.level, camera, item.metadata_json || ''].join(' ').toLowerCase().includes(needle)
  })
})

function positiveRouteId(value: unknown) {
  const raw = Array.isArray(value) ? value[0] : value
  const id = Number(raw || 0)
  return Number.isInteger(id) && id > 0 ? id : null
}
function cameraName(cameraId?: number | null) {
  if (!cameraId) return '-'
  return cameras.value.find((camera) => camera.id === cameraId)?.name || `摄像头 #${cameraId}`
}
function levelType(level: string) {
  const value = level.toLowerCase()
  if (['critical', 'fatal', 'error'].includes(value)) return 'danger'
  if (['warning', 'warn'].includes(value)) return 'warning'
  if (['success', 'recovery', 'recovered'].includes(value)) return 'success'
  return 'info'
}
function levelLabel(level: string) {
  const value = level.toLowerCase()
  if (value === 'critical') return '严重'
  if (value === 'fatal') return '致命'
  if (value === 'error') return '错误'
  if (value === 'warning' || value === 'warn') return '警告'
  if (value === 'info') return '信息'
  if (value === 'success') return '正常'
  return level
}
function categoryLabel(category: string) {
  const labels: Record<string, string> = {
    camera: '摄像头', recorder: '录像', recording: '录像', upload: '上传', storage: '存储',
    system: '系统', ffmpeg: 'FFmpeg', playback: '回放', network: '网络', health: '健康',
  }
  return labels[category.toLowerCase()] || category
}
function parsedMetadata(item: EventItem | null): Record<string, unknown> | null {
  if (!item?.metadata_json) return null
  try {
    const value = JSON.parse(item.metadata_json)
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
  } catch { return null }
}
function metadataText(item: EventItem | null) {
  const parsed = parsedMetadata(item)
  return parsed ? JSON.stringify(parsed, null, 2) : item?.metadata_json || ''
}
function openDetail(item: EventItem) {
  selectedEvent.value = item
  detailVisible.value = true
  void router.replace({ query: { ...route.query, event_id: String(item.id) } })
}
function closeDetail() {
  detailVisible.value = false
  selectedEvent.value = null
  const query = { ...route.query }
  delete query.event_id
  void router.replace({ query })
}
function syncDeepLinkedEvent() {
  const eventId = positiveRouteId(route.query.event_id)
  if (!eventId) return
  const item = events.value.find((event) => event.id === eventId)
  if (item) { selectedEvent.value = item; detailVisible.value = true }
}
function clearFilters() { keyword.value = ''; levelFilter.value = 'all'; categoryFilter.value = 'all'; cameraFilter.value = 'all' }
function relatedAction(item: EventItem) {
  const category = item.category.toLowerCase()
  if (item.recording_id) {
    const query: Record<string, string> = { recording_id: String(item.recording_id) }
    if (item.camera_id) query.camera_id = String(item.camera_id)
    return { label: '打开关联录像', action: () => router.push({ path: '/recordings/manage', query }) }
  }
  if (category === 'upload') return { label: '查看上传管理', action: () => router.push('/uploads') }
  if (item.camera_id || category === 'camera') {
    return { label: '打开摄像头', action: () => item.camera_id ? router.push({ path: '/cameras', query: { camera_id: String(item.camera_id) } }) : router.push('/cameras') }
  }
  return { label: '查看系统健康', action: () => router.push('/health-center') }
}
function wsUrl() {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const cursor = eventCursor === null ? '' : `?after_id=${eventCursor}`
  return `${scheme}//${window.location.host}/ws/events${cursor}`
}
function mergeEvent(item: EventItem) {
  if (events.value.some((existing) => existing.id === item.id)) return
  eventCursor = eventCursor === null ? item.id : Math.max(eventCursor, item.id)
  events.value = [item, ...events.value].sort((a, b) => b.id - a.id).slice(0, 500)
  syncDeepLinkedEvent()
}
function closeSocket() {
  if (!socket) return
  const current = socket
  socket = null
  current.onopen = null; current.onmessage = null; current.onerror = null; current.onclose = null
  try { current.close() } catch { /* already closed */ }
}
function scheduleReconnect() {
  if (!mounted || reconnectTimer !== null) return
  reconnectTimer = window.setTimeout(() => { reconnectTimer = null; connectEventsSocket() }, 2000)
}
function connectEventsSocket() {
  closeSocket()
  if (!mounted) return
  socketState.value = 'connecting'
  const ws = new WebSocket(wsUrl())
  socket = ws
  ws.onopen = () => { if (socket === ws) socketState.value = 'connected' }
  ws.onmessage = (event: MessageEvent) => {
    if (socket !== ws || typeof event.data !== 'string') return
    try {
      const message = JSON.parse(event.data) as { type?: string; data?: EventItem }
      if (message.type === 'event.created' && message.data) mergeEvent(message.data)
    } catch { /* ignore unknown frames */ }
  }
  ws.onerror = () => { if (socket === ws) socketState.value = 'disconnected' }
  ws.onclose = () => { if (socket !== ws) return; socket = null; socketState.value = 'disconnected'; scheduleReconnect() }
}
async function load() {
  loading.value = true
  try {
    const [eventRes] = await Promise.all([
      axios.get<EventItem[]>('/api/events?limit=500'),
      cameraStore.load(),
    ])
    events.value = eventRes.data
    eventCursor = eventRes.data.reduce((maxId, item) => Math.max(maxId, item.id), 0)
    syncDeepLinkedEvent()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '事件加载失败')
  } finally { loading.value = false }
}
async function reload() { await Promise.all([load(), cameraStore.load(true)]); connectEventsSocket() }
watch(() => route.query.event_id, syncDeepLinkedEvent)
onMounted(() => { mounted = true; void (async () => { await load(); connectEventsSocket() })() })
onBeforeUnmount(() => { mounted = false; closeSocket(); if (reconnectTimer !== null) window.clearTimeout(reconnectTimer) })
</script>

<template>
  <div class="events-page" v-loading="loading">
    <div class="actions-row">
      <div class="live-note"><span class="live-dot" :class="{ offline: socketState !== 'connected' }"></span>最近 500 条事件 · {{ liveLabel }}</div>
      <el-button :icon="Refresh" @click="reload">刷新</el-button>
    </div>

    <div class="metrics-grid">
      <button class="metric-card" :class="{ active: levelFilter === 'all' && cameraFilter === 'all' }" @click="levelFilter = 'all'; cameraFilter = 'all'">
        <span>已加载事件</span><strong>{{ events.length }}</strong><small>最近 24h {{ recent24h }}</small>
      </button>
      <button class="metric-card warning" :class="{ active: levelFilter === 'warnings' }" @click="levelFilter = 'warnings'">
        <span>警告</span><strong>{{ warningCount }}</strong><small>warning / warn</small>
      </button>
      <button class="metric-card danger" :class="{ active: levelFilter === 'problems' }" @click="levelFilter = 'problems'">
        <span>错误</span><strong>{{ errorCount }}</strong><small>error / critical / fatal</small>
      </button>
      <button class="metric-card" :class="{ active: cameraFilter === 'affected' }" @click="cameraFilter = 'affected'">
        <span>受影响摄像头</span><strong>{{ affectedCameras }}</strong><small>有 camera_id 的事件</small>
      </button>
    </div>

    <div class="filter-panel">
      <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索消息、事件代码、摄像头或元数据" class="search-box" />
      <el-select v-model="levelFilter" class="filter-select"><el-option label="全部级别" value="all" /><el-option label="警告" value="warnings" /><el-option label="错误" value="problems" /><el-option v-for="item in levelOptions" :key="item" :label="levelLabel(item)" :value="item" /></el-select>
      <el-select v-model="categoryFilter" class="filter-select"><el-option label="全部分类" value="all" /><el-option v-for="item in categories" :key="item" :label="categoryLabel(item)" :value="item" /></el-select>
      <el-select v-model="cameraFilter" class="camera-select"><el-option label="全部摄像头" value="all" /><el-option label="仅受影响摄像头" value="affected" /><el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" /></el-select>
      <el-button link @click="clearFilters">清除筛选</el-button>
    </div>

    <div class="event-table-shell">
      <el-table :data="filteredEvents" row-key="id" height="calc(100vh - 350px)" empty-text="没有符合条件的事件" @row-click="openDetail">
        <el-table-column label="级别" width="92"><template #default="{ row }"><el-tag :type="levelType(row.level)" size="small">{{ levelLabel(row.level) }}</el-tag></template></el-table-column>
        <el-table-column label="分类" width="105"><template #default="{ row }">{{ categoryLabel(row.category) }}</template></el-table-column>
        <el-table-column prop="code" label="事件代码" min-width="170" />
        <el-table-column label="摄像头" min-width="150"><template #default="{ row }">{{ cameraName(row.camera_id) }}</template></el-table-column>
        <el-table-column prop="message" label="消息" min-width="330" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" width="175" />
        <el-table-column label="详情" width="90" fixed="right"><template #default="{ row }"><el-button link type="primary" @click.stop="openDetail(row)">查看</el-button></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="detailVisible" title="事件详情" size="520px" @closed="closeDetail">
      <template v-if="selectedEvent">
        <div class="detail-head"><el-tag :type="levelType(selectedEvent.level)">{{ levelLabel(selectedEvent.level) }}</el-tag><strong>{{ categoryLabel(selectedEvent.category) }}</strong><span>#{{ selectedEvent.id }}</span></div>
        <dl class="detail-grid"><div><dt>事件代码</dt><dd>{{ selectedEvent.code }}</dd></div><div><dt>时间</dt><dd>{{ selectedEvent.created_at }}</dd></div><div><dt>摄像头</dt><dd>{{ cameraName(selectedEvent.camera_id) }}</dd></div><div><dt>录像 ID</dt><dd>{{ selectedEvent.recording_id || '-' }}</dd></div><div class="wide"><dt>消息</dt><dd>{{ selectedEvent.message }}</dd></div></dl>
        <div v-if="metadataText(selectedEvent)" class="metadata-block"><div>元数据</div><pre>{{ metadataText(selectedEvent) }}</pre></div>
        <div class="drawer-actions"><el-button type="primary" @click="relatedAction(selectedEvent).action()">{{ relatedAction(selectedEvent).label }}</el-button></div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.events-page{max-width:1650px;margin:0 auto;padding:20px 24px 30px}.actions-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}.live-note{display:flex;align-items:center;gap:7px;color:var(--nvr-muted);font-size:10px}.live-dot{width:6px;height:6px;border-radius:50%;background:var(--nvr-green)}.live-dot.offline{background:var(--nvr-yellow)}.metrics-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:10px}.metric-card{appearance:none;min-height:82px;display:grid;grid-template-columns:auto 1fr;align-items:end;column-gap:8px;row-gap:4px;padding:12px 14px;border:1px solid var(--nvr-border);border-radius:9px;color:var(--nvr-text);background:var(--nvr-surface);cursor:pointer;text-align:left}.metric-card:hover,.metric-card.active{border-color:color-mix(in srgb,var(--nvr-blue) 34%,var(--nvr-border));background:color-mix(in srgb,var(--nvr-blue) 5%,var(--nvr-surface))}.metric-card span{grid-column:1/-1;color:var(--nvr-muted);font-size:10px}.metric-card strong{font-size:22px;line-height:1}.metric-card small{justify-self:end;color:var(--nvr-subtle);font-size:8px}.metric-card.warning strong{color:var(--nvr-yellow)}.metric-card.danger strong{color:var(--nvr-red)}.filter-panel{display:flex;align-items:center;gap:8px;margin-bottom:10px;padding:9px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.search-box{flex:1;min-width:250px}.filter-select{width:135px}.camera-select{width:180px}.event-table-shell{overflow:hidden;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.detail-head{display:flex;align-items:center;gap:9px;padding-bottom:14px;border-bottom:1px solid var(--nvr-border)}.detail-head strong{font-size:13px}.detail-head span{margin-left:auto;color:var(--nvr-subtle);font-size:9px}.detail-grid{margin:14px 0 0}.detail-grid>div{display:grid;grid-template-columns:105px minmax(0,1fr);gap:12px;padding:9px 0;border-bottom:1px solid var(--nvr-border)}.detail-grid dt{color:var(--nvr-muted);font-size:10px}.detail-grid dd{margin:0;font-size:10px;overflow-wrap:anywhere}.metadata-block{margin-top:14px}.metadata-block>div{margin-bottom:6px;color:var(--nvr-muted);font-size:9px}.metadata-block pre{max-height:280px;overflow:auto;margin:0;padding:10px;border:1px solid var(--nvr-border);border-radius:7px;color:var(--nvr-text-soft);background:var(--nvr-bg-soft);font-size:9px;white-space:pre-wrap}.drawer-actions{display:flex;justify-content:flex-end;margin-top:16px}@media(max-width:900px){.metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.filter-panel{align-items:stretch;flex-direction:column}.search-box,.filter-select,.camera-select{width:100%}}@media(max-width:620px){.events-page{padding:14px}.metrics-grid{grid-template-columns:1fr 1fr}}
</style>