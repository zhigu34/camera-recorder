<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Refresh, Search, WarningFilled } from '@element-plus/icons-vue'

interface Camera {
  id: number
  name: string
}

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

const emit = defineEmits<{
  (event: 'open-cameras'): void
  (event: 'open-recordings'): void
  (event: 'open-uploads'): void
  (event: 'open-health'): void
}>()

const events = ref<EventItem[]>([])
const cameras = ref<Camera[]>([])
const loading = ref(false)
const keyword = ref('')
const levelFilter = ref('all')
const categoryFilter = ref('all')
const cameraFilter = ref<number | 'all'>('all')
const detailVisible = ref(false)
const selectedEvent = ref<EventItem | null>(null)
let timer: number | null = null

const categories = computed(() => Array.from(new Set(events.value.map((item) => item.category).filter(Boolean))).sort())
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

const filteredEvents = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  return events.value.filter((item) => {
    if (levelFilter.value !== 'all' && item.level !== levelFilter.value) return false
    if (categoryFilter.value !== 'all' && item.category !== categoryFilter.value) return false
    if (cameraFilter.value !== 'all' && item.camera_id !== cameraFilter.value) return false
    if (!needle) return true
    const camera = cameraName(item.camera_id)
    return [item.message, item.code, item.category, item.level, camera, item.metadata_json || '']
      .join(' ')
      .toLowerCase()
      .includes(needle)
  })
})

const levelOptions = computed(() => Array.from(new Set(events.value.map((item) => item.level).filter(Boolean))).sort())

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
  } catch {
    return null
  }
}

function metadataText(item: EventItem | null) {
  const parsed = parsedMetadata(item)
  if (parsed) return JSON.stringify(parsed, null, 2)
  return item?.metadata_json || ''
}

function openDetail(item: EventItem) {
  selectedEvent.value = item
  detailVisible.value = true
}

function clearFilters() {
  keyword.value = ''
  levelFilter.value = 'all'
  categoryFilter.value = 'all'
  cameraFilter.value = 'all'
}

function relatedAction(item: EventItem) {
  const category = item.category.toLowerCase()
  if (item.recording_id || ['recording', 'recorder', 'playback'].includes(category)) return { label: '查看录像管理', action: () => emit('open-recordings') }
  if (category === 'upload') return { label: '查看上传管理', action: () => emit('open-uploads') }
  if (item.camera_id || category === 'camera') return { label: '查看摄像头', action: () => emit('open-cameras') }
  return { label: '查看系统健康', action: () => emit('open-health') }
}

async function load() {
  loading.value = true
  try {
    const [eventRes, cameraRes] = await Promise.all([
      axios.get<EventItem[]>('/api/events?limit=500'),
      axios.get<Camera[]>('/api/cameras'),
    ])
    events.value = eventRes.data
    cameras.value = cameraRes.data
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '事件加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
  timer = window.setInterval(() => void load(), 15000)
})

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<template>
  <div class="events-page" v-loading="loading">
    <div class="actions-row">
      <div class="live-note"><span class="live-dot"></span>最近 500 条事件 · 每 15 秒自动刷新</div>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </div>

    <div class="metrics-grid">
      <button class="metric-card" :class="{ active: levelFilter === 'all' }" @click="levelFilter = 'all'">
        <span>已加载事件</span><strong>{{ events.length }}</strong><small>最近 24h {{ recent24h }}</small>
      </button>
      <button class="metric-card warning" @click="levelFilter = levelOptions.includes('warning') ? 'warning' : 'all'">
        <span>警告</span><strong>{{ warningCount }}</strong><small>需要关注</small>
      </button>
      <button class="metric-card danger" @click="levelFilter = levelOptions.includes('error') ? 'error' : levelOptions.includes('critical') ? 'critical' : 'all'">
        <span>错误 / 严重</span><strong>{{ errorCount }}</strong><small>优先处理</small>
      </button>
      <button class="metric-card" @click="cameraFilter = 'all'">
        <span>涉及摄像头</span><strong>{{ affectedCameras }}</strong><small>有事件关联</small>
      </button>
    </div>

    <div class="filter-bar">
      <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索消息、事件码、分类、摄像头或元数据" class="search-input" />
      <el-select v-model="levelFilter" class="filter-select" placeholder="级别">
        <el-option label="全部级别" value="all" />
        <el-option v-for="level in levelOptions" :key="level" :label="levelLabel(level)" :value="level" />
      </el-select>
      <el-select v-model="categoryFilter" class="filter-select" placeholder="分类">
        <el-option label="全部分类" value="all" />
        <el-option v-for="category in categories" :key="category" :label="categoryLabel(category)" :value="category" />
      </el-select>
      <el-select v-model="cameraFilter" class="camera-select" filterable placeholder="摄像头">
        <el-option label="全部摄像头" value="all" />
        <el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" />
      </el-select>
      <el-button text @click="clearFilters">清除筛选</el-button>
      <span class="result-count">{{ filteredEvents.length }} 条</span>
    </div>

    <div class="table-panel">
      <el-table :data="filteredEvents" height="calc(100vh - 318px)" empty-text="暂无匹配事件" @row-click="openDetail">
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column label="级别" width="88">
          <template #default="{ row }"><el-tag size="small" :type="levelType(row.level)">{{ levelLabel(row.level) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="分类" width="108"><template #default="{ row }">{{ categoryLabel(row.category) }}</template></el-table-column>
        <el-table-column prop="code" label="事件码" min-width="150" show-overflow-tooltip />
        <el-table-column label="摄像头" min-width="145" show-overflow-tooltip><template #default="{ row }">{{ cameraName(row.camera_id) }}</template></el-table-column>
        <el-table-column prop="message" label="消息" min-width="320" show-overflow-tooltip />
        <el-table-column label="关联" width="110">
          <template #default="{ row }">
            <span v-if="row.recording_id" class="relation">录像 #{{ row.recording_id }}</span>
            <span v-else-if="row.camera_id" class="relation">摄像头 #{{ row.camera_id }}</span>
            <span v-else class="muted">系统</span>
          </template>
        </el-table-column>
        <el-table-column label="" width="52" fixed="right"><template #default><span class="open-arrow">›</span></template></el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="detailVisible" title="事件详情" size="460px">
      <template v-if="selectedEvent">
        <div class="detail-hero" :class="levelType(selectedEvent.level)">
          <WarningFilled class="detail-icon" />
          <div><el-tag size="small" :type="levelType(selectedEvent.level)">{{ levelLabel(selectedEvent.level) }}</el-tag><strong>{{ selectedEvent.message }}</strong><span>{{ selectedEvent.created_at }}</span></div>
        </div>
        <dl class="detail-list">
          <div><dt>事件 ID</dt><dd>#{{ selectedEvent.id }}</dd></div>
          <div><dt>分类</dt><dd>{{ categoryLabel(selectedEvent.category) }}</dd></div>
          <div><dt>事件码</dt><dd><code>{{ selectedEvent.code }}</code></dd></div>
          <div><dt>摄像头</dt><dd>{{ cameraName(selectedEvent.camera_id) }}</dd></div>
          <div><dt>录像</dt><dd>{{ selectedEvent.recording_id ? `#${selectedEvent.recording_id}` : '-' }}</dd></div>
        </dl>
        <div v-if="selectedEvent.metadata_json" class="metadata-block">
          <div class="section-label">元数据</div>
          <pre>{{ metadataText(selectedEvent) }}</pre>
        </div>
        <div class="drawer-actions">
          <el-button type="primary" @click="relatedAction(selectedEvent).action()">{{ relatedAction(selectedEvent).label }}</el-button>
          <el-button @click="detailVisible = false">关闭</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.events-page{padding:18px 20px 28px;color:var(--nvr-text)}
.actions-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.live-note{display:flex;align-items:center;gap:8px;color:var(--nvr-muted);font-size:12px}.live-dot{width:7px;height:7px;border-radius:50%;background:var(--nvr-green);box-shadow:0 0 0 4px rgba(46,204,138,.08)}
.metrics-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:12px}.metric-card{appearance:none;display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:14px 16px;color:var(--nvr-text);background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px;cursor:pointer;text-align:left}.metric-card:hover,.metric-card.active{border-color:rgba(76,141,255,.45);background:var(--nvr-surface-2)}.metric-card span{font-size:11px;color:var(--nvr-muted)}.metric-card strong{font-size:24px;font-weight:650;line-height:1}.metric-card small{font-size:10px;color:#647387}.metric-card.warning strong{color:var(--nvr-yellow)}.metric-card.danger strong{color:var(--nvr-red)}
.filter-bar{display:flex;align-items:center;gap:8px;margin-bottom:10px;padding:10px;background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px}.search-input{min-width:280px;flex:1}.filter-select{width:126px}.camera-select{width:170px}.result-count{margin-left:auto;color:var(--nvr-muted);font-size:11px;white-space:nowrap}
.table-panel{overflow:hidden;background:var(--nvr-surface);border:1px solid var(--nvr-border);border-radius:10px}.relation{color:#9db8df;font-size:11px}.muted{color:var(--nvr-muted)}.open-arrow{color:#647387;font-size:20px}.table-panel :deep(.el-table__row){cursor:pointer}
.detail-hero{display:flex;gap:12px;padding:14px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface-2)}.detail-icon{flex:0 0 22px;width:22px;margin-top:2px;color:var(--nvr-muted)}.detail-hero.warning .detail-icon{color:var(--nvr-yellow)}.detail-hero.danger .detail-icon{color:var(--nvr-red)}.detail-hero>div{display:flex;min-width:0;flex-direction:column;align-items:flex-start;gap:7px}.detail-hero strong{font-size:14px;line-height:1.55}.detail-hero span{color:var(--nvr-muted);font-size:11px}.detail-list{margin:16px 0}.detail-list>div{display:grid;grid-template-columns:90px minmax(0,1fr);padding:9px 0;border-bottom:1px solid var(--nvr-border)}.detail-list dt{color:var(--nvr-muted);font-size:11px}.detail-list dd{margin:0;font-size:12px;word-break:break-all}.detail-list code{font-size:11px;color:#a9c8f5}.section-label{margin-bottom:7px;color:var(--nvr-muted);font-size:10px;font-weight:700;letter-spacing:.08em}.metadata-block pre{max-height:280px;overflow:auto;margin:0;padding:12px;color:#aeb9c6;background:#0c1117;border:1px solid var(--nvr-border);border-radius:8px;font-size:11px;line-height:1.55;white-space:pre-wrap;word-break:break-all}.drawer-actions{display:flex;gap:8px;margin-top:18px}
@media(max-width:1000px){.metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.filter-bar{flex-wrap:wrap}.search-input{flex-basis:100%}.result-count{margin-left:0}}
@media(max-width:640px){.events-page{padding:12px}.metrics-grid{grid-template-columns:1fr 1fr}.filter-select,.camera-select{width:calc(50% - 4px)}}
</style>
