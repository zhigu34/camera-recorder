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
    return { label: '打开关联录像', action: () => router.push({ path: '/recordings/browser', query }) }
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
        <span>错误 / 严重</span><strong>{{ errorCount }}</strong><small>error / critical / fatal</small>
      </button>
      <button class="metric-card" :class="{ active: cameraFilter === 'affected' }" @click="cameraFilter = 'affected'">
        <span>涉及摄像头</span><strong>{{ affectedCameras }}</strong><small>仅显示设备相关事件</small>
      </button>
    </div>

    <div class="filter-bar">
      <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索消息、事件码、分类、摄像头或元数据" class="search-input" />
      <el-select v-model="levelFilter" class="filter-select" placeholder="级别">
        <el-option label="全部级别" value="all" /><el-option label="警告类" value="warnings" /><el-option label="错误 / 严重" value="problems" />
        <el-option v-for="level in levelOptions" :key="level" :label="levelLabel(level)" :value="level" />
      </el-select>
      <el-select v-model="categoryFilter" class="filter-select" placeholder="分类">
        <el-option label="全部分类" value="all" /><el-option v-for="category in categories" :key="category" :label="categoryLabel(category)" :value="category" />
      </el-select>
      <el-select v-model="cameraFilter" class="camera-select" filterable placeholder="摄像头">
        <el-option label="全部摄像头" value="all" /><el-option label="所有设备相关事件" value="affected" /><el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" />
      </el-select>
      <el-button text @click="clearFilters">清除筛选</el-button><span class="result-count">{{ filteredEvents.length }} 条</span>
    </div>

    <div class="table-panel">
      <el-table :data="filteredEvents" height="calc(100vh - 318px)" empty-text="暂无匹配事件" @row-click="openDetail">
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column label="级别" width="88"><template #default="{ row }"><el-tag size="small" :type="levelType(row.level)">{{ levelLabel(row.level) }}</el-tag></template></el-table-column>
        <el-table-column label="分类" width="108"><template #default="{ row }">{{ categoryLabel(row.category) }}</template></el-table-column>
        <el-table-column prop="code" label="事件码" min-width="150" show-overflow-tooltip />
        <el-table-column label="摄像头" min-width="145" show-overflow-tooltip><template #default="{ row }">{{ cameraName(row.camera_id) }}</template></el-table-column>
        <el-table-column prop="message" label="消息" min-width="320" show-overflow-tooltip />
        <el-table-column label="关联" width="110"><template #default="{ row }"><span v-if="row.recording_id" class="relation">录像 #{{ row.recording_id }}</span><span v-else-if="row.camera_id" class="relation">摄像头 #{{ row.camera_id }}</span><span v-else class="muted">系统</span></template></el-table-column>
        <el-table-column label="" width="52" fixed="right"><template #default><span class="open-arrow">›</span></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="detailVisible" title="事件详情" size="460px" @closed="closeDetail">
      <template v-if="selectedEvent">
        <div class="detail-hero" :class="levelType(selectedEvent.level)"><WarningFilled class="detail-icon" /><div><el-tag size="small" :type="levelType(selectedEvent.level)">{{ levelLabel(selectedEvent.level) }}</el-tag><strong>{{ selectedEvent.message }}</strong><span>{{ selectedEvent.created_at }}</span></div></div>
        <dl class="detail-list">
          <div><dt>事件 ID</dt><dd>#{{ selectedEvent.id }}</dd></div><div><dt>分类</dt><dd>{{ categoryLabel(selectedEvent.category) }}</dd></div><div><dt>事件码</dt><dd><code>{{ selectedEvent.code }}</code></dd></div><div><dt>摄像头</dt><dd>{{ cameraName(selectedEvent.camera_id) }}</dd></div><div><dt>录像</dt><dd>{{ selectedEvent.recording_id ? `#${selectedEvent.recording_id}` : '-' }}</dd></div>
        </dl>
        <div v-if="selectedEvent.metadata_json" class="metadata-block"><div class="section-label">元数据</div><pre>{{ metadataText(selectedEvent) }}</pre></div>
        <div class="drawer-actions"><el-button type="primary" @click="relatedAction(selectedEvent).action()">{{ relatedAction(selectedEvent).label }}</el-button><el-button @click="closeDetail">关闭</el-button></div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.events-page{padding:18px 20px 28px;color:var(--nvr-text)}
.actions-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.live-note{display:flex;align-items:center;gap:8px;color:var(--nvr-muted);font-size:12px}.live-dot{width:7px;height:7px;border-radius:50%;background:var(--nvr-green);box-shadow:0 0 0 4px color-mix(in srgb,var(--nvr-green) 8%,transparent)}.live-dot.offline{background:var(--nvr-yellow);box-shadow:0 0 0 4px color-mix(in srgb,var(--nvr-yellow) 8%,transparent)}
.metrics-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:12px}.metric-card{appearance:none;display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:14px 16px;color:var(--nvr-text);background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px;cursor:pointer;text-align:left}.metric-card:hover,.metric-card.active{border-color:color-mix(in srgb,var(--nvr-blue) 45%,var(--nvr-border));background:var(--nvr-surface-2)}.metric-card span{font-size:11px;color:var(--nvr-muted)}.metric-card strong{font-size:24px;font-weight:650;line-height:1}.metric-card small{font-size:10px;color:var(--nvr-subtle)}.metric-card.warning strong{color:var(--nvr-yellow)}.metric-card.danger strong{color:var(--nvr-red)}
.filter-bar{display:flex;align-items:center;gap:8px;margin-bottom:10px;padding:10px;background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px}.search-input{min-width:280px;flex:1}.filter-select{width:126px}.camera-select{width:170px}.result-count{margin-left:auto;color:var(--nvr-muted);font-size:11px;white-space:nowrap}
.table-panel{overflow:hidden;background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px}.relation{color:color-mix(in srgb,var(--nvr-blue) 58%,var(--nvr-text));font-size:11px}.muted{color:var(--nvr-muted)}.open-arrow{color:var(--nvr-subtle);font-size:20px}.table-panel :deep(.el-table__row){cursor:pointer}
.detail-hero{display:flex;gap:12px;padding:14px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface-2)}.detail-icon{flex:0 0 22px;width:22px;margin-top:2px;color:var(--nvr-muted)}.detail-hero.warning .detail-icon{color:var(--nvr-yellow)}.detail-hero.danger .detail-icon{color:var(--nvr-red)}.detail-hero>div{display:flex;min-width:0;flex-direction:column;align-items:flex-start;gap:7px}.detail-hero strong{font-size:14px;line-height:1.55}.detail-hero span{color:var(--nvr-muted);font-size:11px}.detail-list{margin:16px 0}.detail-list>div{display:grid;grid-template-columns:90px minmax(0,1fr);padding:9px 0;border-bottom:1px solid var(--nvr-border)}.detail-list dt{color:var(--nvr-muted);font-size:11px}.detail-list dd{margin:0;font-size:12px;word-break:break-all}.detail-list code{font-size:11px;color:color-mix(in srgb,var(--nvr-blue) 62%,var(--nvr-text))}.section-label{margin-bottom:7px;color:var(--nvr-muted);font-size:10px;font-weight:700;letter-spacing:.08em}.metadata-block pre{max-height:280px;overflow:auto;margin:0;padding:12px;color:var(--nvr-text-soft);background:var(--nvr-surface-2);border:1px solid var(--nvr-border);border-radius:8px;font-size:11px;line-height:1.55;white-space:pre-wrap;word-break:break-all}.drawer-actions{display:flex;gap:8px;margin-top:18px}
@media(max-width:1000px){.metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.filter-bar{flex-wrap:wrap}.search-input{flex-basis:100%}.result-count{margin-left:0}}
@media(max-width:640px){.events-page{padding:12px}.metrics-grid{grid-template-columns:1fr 1fr}.filter-select,.camera-select{width:calc(50% - 4px)}}
</style>
