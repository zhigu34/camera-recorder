<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Cloudy, Refresh, Search, Setting, UploadFilled, WarningFilled } from '@element-plus/icons-vue'
import { useCameraStore } from './stores/cameras'
import { parsePositiveQueryId } from './utils/adminDeepLinks'
import { formatDateTime } from './utils/dateTime'

interface UploadTask {
  id: number
  recording_id: number
  provider: string
  remote_path: string
  status: string
  retry_count: number
  last_error?: string | null
  started_at?: string | null
  completed_at?: string | null
  next_retry_at?: string | null
  created_at: string
  updated_at: string
}

interface UploadStatus {
  enabled: boolean
  configured: boolean
  active: boolean
  provider: string
  webdav_url: string
  webdav_root: string
  local_retention_hours: number
  counts: Record<string, number>
}

interface Recording {
  id: number
  camera_id: number
  mp4_path: string
  file_size?: number | null
  started_at?: string | null
  upload_status: string
}

interface UploadStreamMessage {
  type?: 'uploads.snapshot' | 'uploads.delta'
  tasks?: UploadTask[]
  removed_ids?: number[]
  status?: UploadStatus
}

const emit = defineEmits<{
  (event: 'open-settings'): void
  (event: 'open-recordings'): void
}>()

const route = useRoute()
const router = useRouter()
const cameraStore = useCameraStore()
const { cameras } = storeToRefs(cameraStore)

const loading = ref(false)
const scanning = ref(false)
const tasks = ref<UploadTask[]>([])
const status = ref<UploadStatus | null>(null)
const recordings = ref<Recording[]>([])
const searchText = ref('')
const statusFilter = ref('')
const detailVisible = ref(false)
const activeTask = ref<UploadTask | null>(null)
const streamConnected = ref(false)
let referencesRefreshing = false
let socket: WebSocket | null = null
let reconnectTimer: number | null = null
let mounted = false

const recordingMap = computed(() => new Map(recordings.value.map((row) => [row.id, row])))
const cameraMap = computed(() => new Map(cameras.value.map((row) => [row.id, row])))
const routeCameraId = computed(() => parsePositiveQueryId(route.query.camera_id))
const counts = computed(() => status.value?.counts || {})
const cameraScopedTasks = computed(() => {
  if (!routeCameraId.value) return tasks.value
  return tasks.value.filter((task) => recordingMap.value.get(task.recording_id)?.camera_id === routeCameraId.value)
})
const scopedCounts = computed(() => {
  if (!routeCameraId.value) return counts.value
  return cameraScopedTasks.value.reduce<Record<string, number>>((result, task) => {
    result[task.status] = (result[task.status] || 0) + 1
    return result
  }, {})
})
const totalCount = computed(() => Object.values(scopedCounts.value).reduce((sum, value) => sum + Number(value || 0), 0))
const pendingCount = computed(() => (scopedCounts.value.pending || 0) + (scopedCounts.value.uploading || 0) + (scopedCounts.value.retry_wait || 0))
const successCount = computed(() => scopedCounts.value.success || 0)
const failedCount = computed(() => scopedCounts.value.failed || 0)
const filteredTasks = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  return cameraScopedTasks.value.filter((task) => {
    if (statusFilter.value && task.status !== statusFilter.value) return false
    const recording = recordingMap.value.get(task.recording_id)
    if (routeCameraId.value && recording?.camera_id !== routeCameraId.value) return false
    if (!keyword) return true
    const camera = recording ? cameraMap.value.get(recording.camera_id) : null
    const fileName = recording?.mp4_path.split('/').pop() || ''
    return `${task.id} ${task.recording_id} ${camera?.name || ''} ${camera?.ip || ''} ${fileName} ${task.remote_path} ${task.last_error || ''}`.toLowerCase().includes(keyword)
  })
})

function providerLabel(value?: string | null) {
  if (value === 'openlist_webdav') return 'OpenList WebDAV'
  return value || 'OpenList WebDAV'
}

function taskLabel(value: string) {
  if (value === 'pending') return '待上传'
  if (value === 'uploading') return '上传中'
  if (value === 'retry_wait') return '等待重试'
  if (value === 'success') return '已完成'
  if (value === 'failed') return '失败'
  return value
}

function taskType(value: string) {
  if (value === 'success') return 'success'
  if (value === 'failed') return 'danger'
  if (value === 'retry_wait') return 'warning'
  if (value === 'uploading') return 'primary'
  return 'info'
}

function recordingFor(task: UploadTask) {
  return recordingMap.value.get(task.recording_id)
}

function cameraName(task: UploadTask) {
  const recording = recordingFor(task)
  if (!recording) return '-'
  return cameraMap.value.get(recording.camera_id)?.name || `摄像头 #${recording.camera_id}`
}

function fileName(task: UploadTask) {
  const recordingPath = recordingFor(task)?.mp4_path || ''
  if (recordingPath) return recordingPath.split('/').pop() || recordingPath
  return task.remote_path.split('/').pop() || task.remote_path || '-'
}

function formatTime(value?: string | null) {
  return formatDateTime(value)
}

function formatBytes(bytes?: number | null) {
  const value = Number(bytes || 0)
  if (!value) return '-'
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}

function clearTaskDeepLink() {
  const nextQuery = { ...route.query }
  delete nextQuery.task_id
  void router.replace({ path: '/uploads', query: nextQuery })
}

function syncDeepLinkedTask(showMissing = false) {
  const taskId = parsePositiveQueryId(route.query.task_id)
  if (taskId === null) {
    detailVisible.value = false
    activeTask.value = null
    return
  }
  const task = tasks.value.find((item) => item.id === taskId)
  if (!task) {
    if (showMissing) ElMessage.warning(`未找到上传任务 #${taskId}`)
    detailVisible.value = false
    activeTask.value = null
    clearTaskDeepLink()
    return
  }
  activeTask.value = task
  detailVisible.value = true
}

function openDetail(task: UploadTask) {
  activeTask.value = task
  detailVisible.value = true
  void router.push({ path: '/uploads', query: { ...route.query, task_id: String(task.id) } })
}

function closeDetail() {
  detailVisible.value = false
  activeTask.value = null
  if (parsePositiveQueryId(route.query.task_id) !== null) clearTaskDeepLink()
}

async function refreshReferences() {
  if (referencesRefreshing) return
  referencesRefreshing = true
  try {
    const [recordingRes] = await Promise.all([
      axios.get<Recording[]>('/api/recordings?limit=1000'),
      cameraStore.load(true),
    ])
    recordings.value = recordingRes.data
  } catch {
    // Keep the previous maps; task rows can still fall back to remote path / IDs.
  } finally {
    referencesRefreshing = false
  }
}

function refreshReferencesIfNeeded(incoming: UploadTask[]) {
  if (incoming.some((task) => !recordingMap.value.has(task.recording_id))) {
    void refreshReferences()
  }
}

function applyTasks(incoming: UploadTask[], removedIds: number[] = []) {
  const byId = new Map(tasks.value.map((task) => [task.id, task]))
  removedIds.forEach((id) => byId.delete(id))
  incoming.forEach((task) => byId.set(task.id, task))
  tasks.value = Array.from(byId.values()).sort((a, b) => b.id - a.id).slice(0, 1000)
  if (activeTask.value) {
    const current = byId.get(activeTask.value.id)
    if (current) activeTask.value = current
    else closeDetail()
  }
  refreshReferencesIfNeeded(incoming)
  syncDeepLinkedTask(false)
}

function wsUrl() {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${window.location.host}/ws/uploads`
}

function closeSocket() {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (socket) {
    const current = socket
    socket = null
    current.onopen = null
    current.onmessage = null
    current.onerror = null
    current.onclose = null
    try { current.close() } catch { /* already closed */ }
  }
  streamConnected.value = false
}

function scheduleReconnect() {
  if (!mounted || reconnectTimer !== null) return
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null
    connectStream()
  }, 2000)
}

function connectStream() {
  closeSocket()
  if (!mounted) return
  const ws = new WebSocket(wsUrl())
  socket = ws
  ws.onopen = () => {
    if (socket !== ws) return
    streamConnected.value = true
  }
  ws.onmessage = (event) => {
    if (socket !== ws || typeof event.data !== 'string') return
    try {
      const message = JSON.parse(event.data) as UploadStreamMessage
      if (message.type === 'uploads.snapshot') {
        tasks.value = (message.tasks || []).slice(0, 1000)
        if (message.status) status.value = message.status
        refreshReferencesIfNeeded(tasks.value)
        syncDeepLinkedTask(false)
      } else if (message.type === 'uploads.delta') {
        applyTasks(message.tasks || [], message.removed_ids || [])
        if (message.status) status.value = message.status
      }
    } catch {
      // Ignore malformed frames and keep the last valid snapshot.
    }
  }
  ws.onerror = () => {
    if (socket === ws) streamConnected.value = false
  }
  ws.onclose = () => {
    if (socket !== ws) return
    socket = null
    streamConnected.value = false
    scheduleReconnect()
  }
}

async function retry(task: UploadTask) {
  try {
    await axios.post(`/api/uploads/tasks/${task.id}/retry`)
    task.status = 'pending'
    task.retry_count = 0
    task.next_retry_at = null
    task.last_error = null
    ElMessage.success(`任务 #${task.id} 已重新排队`)
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '重试失败')
  }
}

async function scan() {
  scanning.value = true
  try {
    await axios.post('/api/uploads/scan')
    ElMessage.success('OpenList 上传扫描已完成')
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '上传扫描失败')
  } finally {
    scanning.value = false
  }
}

async function load(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const [statusRes, taskRes, recordingRes] = await Promise.all([
      axios.get<UploadStatus>('/api/uploads'),
      axios.get<UploadTask[]>('/api/uploads/tasks?limit=1000'),
      axios.get<Recording[]>('/api/recordings?limit=1000'),
      cameraStore.load(),
    ])
    status.value = statusRes.data
    tasks.value = taskRes.data
    recordings.value = recordingRes.data
    syncDeepLinkedTask(false)
  } catch (error) {
    if (showLoading) ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '上传管理加载失败')
  } finally {
    if (showLoading) loading.value = false
  }
}

watch(() => route.query.task_id, () => syncDeepLinkedTask(false))
watch(() => route.query.camera_id, () => { if (activeTask.value && !filteredTasks.value.some((item) => item.id === activeTask.value?.id)) closeDetail() })
onMounted(() => {
  mounted = true
  void load().then(() => syncDeepLinkedTask(true)).finally(connectStream)
})
onBeforeUnmount(() => {
  mounted = false
  closeSocket()
})
</script>

<template>
  <div class="upload-page" v-loading="loading">
    <section class="provider-panel">
      <div class="provider-main">
        <span class="provider-icon"><Cloudy /></span>
        <div>
          <strong>{{ providerLabel(status?.provider) }}</strong>
          <span>OpenList 只是统一存储入口，实际后端可以挂载任意支持的网盘或对象存储。</span>
        </div>
      </div>
      <div class="provider-state">
        <el-tag :type="status?.active ? 'success' : status?.configured ? 'warning' : 'danger'">
          {{ status?.active ? '自动上传运行中' : status?.configured ? '已配置但未启用' : '尚未配置' }}
        </el-tag>
        <el-button @click="emit('open-settings')"><Setting class="button-icon" />上传设置</el-button>
      </div>
      <div class="provider-meta">
        <span><b>WebDAV</b>{{ status?.webdav_url || '-' }}</span>
        <span><b>归档目录</b>{{ status?.webdav_root || '-' }}</span>
        <span><b>本地保留</b>{{ status?.local_retention_hours === -1 ? '永久' : `${status?.local_retention_hours ?? '-'} 小时` }}</span>
      </div>
    </section>

    <section class="summary-grid">
      <article class="summary-card"><span><UploadFilled /></span><div><small>上传任务</small><strong>{{ totalCount }}</strong></div></article>
      <article class="summary-card"><span><Refresh /></span><div><small>待处理</small><strong>{{ pendingCount }}</strong></div></article>
      <article class="summary-card"><span><Cloudy /></span><div><small>已完成</small><strong>{{ successCount }}</strong></div></article>
      <article class="summary-card" :class="{ danger: failedCount > 0 }"><span><WarningFilled /></span><div><small>失败</small><strong>{{ failedCount }}</strong></div></article>
    </section>

    <section class="panel toolbar-panel">
      <div class="toolbar-left">
        <el-input v-model="searchText" clearable placeholder="搜索摄像头、文件名、远端路径或错误" class="search-box">
          <template #prefix><Search /></template>
        </el-input>
        <el-select v-model="statusFilter" clearable placeholder="全部状态" class="status-select">
          <el-option label="待上传" value="pending" />
          <el-option label="上传中" value="uploading" />
          <el-option label="等待重试" value="retry_wait" />
          <el-option label="已完成" value="success" />
          <el-option label="失败" value="failed" />
        </el-select>
      </div>
      <div class="toolbar-actions">
        <span v-if="routeCameraId" class="stream-state live"><i></i>摄像头 #{{ routeCameraId }}</span>
        <span class="stream-state" :class="{ live: streamConnected }"><i></i>{{ streamConnected ? '实时推送' : '正在重连' }}</span>
        <span>显示 {{ filteredTasks.length }} / {{ tasks.length }} 条</span>
        <el-button @click="emit('open-recordings')">录像管理</el-button>
        <el-button @click="load()">刷新</el-button>
        <el-button type="primary" :loading="scanning" :disabled="!status?.active" @click="scan">立即扫描</el-button>
      </div>
    </section>

    <section class="panel table-panel">
      <el-table :data="filteredTasks" height="calc(100vh - 390px)" empty-text="暂无上传任务">
        <el-table-column prop="id" label="任务" width="82" fixed="left" />
        <el-table-column label="录像" min-width="240">
          <template #default="{ row }">
            <div class="recording-cell"><strong>{{ cameraName(row) }}</strong><span>{{ fileName(row) }}</span></div>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="105"><template #default="{ row }">{{ formatBytes(recordingFor(row)?.file_size) }}</template></el-table-column>
        <el-table-column label="状态" width="115"><template #default="{ row }"><el-tag :type="taskType(row.status)" size="small">{{ taskLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="retry_count" label="重试" width="75" />
        <el-table-column label="远端路径" min-width="340"><template #default="{ row }"><span class="path-cell">{{ row.remote_path }}</span></template></el-table-column>
        <el-table-column label="更新时间" width="175"><template #default="{ row }"><span class="muted">{{ formatTime(row.updated_at) }}</span></template></el-table-column>
        <el-table-column label="最近错误" min-width="220"><template #default="{ row }"><span :class="row.last_error ? 'error-text' : 'muted'">{{ row.last_error || '-' }}</span></template></el-table-column>
        <el-table-column label="操作" width="145" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row)">详情</el-button>
            <el-button v-if="row.status === 'failed' || row.status === 'retry_wait'" size="small" type="warning" plain @click="retry(row)">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-drawer v-model="detailVisible" title="上传任务详情" size="460px" @closed="closeDetail">
      <template v-if="activeTask">
        <div class="drawer-head">
          <strong>任务 #{{ activeTask.id }}</strong>
          <el-tag :type="taskType(activeTask.status)">{{ taskLabel(activeTask.status) }}</el-tag>
        </div>
        <dl class="detail-list">
          <div><dt>摄像头</dt><dd>{{ cameraName(activeTask) }}</dd></div>
          <div><dt>录像 ID</dt><dd>#{{ activeTask.recording_id }}</dd></div>
          <div><dt>文件</dt><dd>{{ fileName(activeTask) }}</dd></div>
          <div><dt>文件大小</dt><dd>{{ formatBytes(recordingFor(activeTask)?.file_size) }}</dd></div>
          <div><dt>Provider</dt><dd>{{ providerLabel(activeTask.provider) }}</dd></div>
          <div><dt>重试次数</dt><dd>{{ activeTask.retry_count }}</dd></div>
          <div><dt>创建时间</dt><dd>{{ formatTime(activeTask.created_at) }}</dd></div>
          <div><dt>开始时间</dt><dd>{{ formatTime(activeTask.started_at) }}</dd></div>
          <div><dt>完成时间</dt><dd>{{ formatTime(activeTask.completed_at) }}</dd></div>
          <div><dt>下次重试</dt><dd>{{ formatTime(activeTask.next_retry_at) }}</dd></div>
          <div class="wide"><dt>远端路径</dt><dd>{{ activeTask.remote_path }}</dd></div>
          <div v-if="activeTask.last_error" class="wide error-row"><dt>最近错误</dt><dd>{{ activeTask.last_error }}</dd></div>
        </dl>
        <div class="drawer-actions">
          <el-button @click="emit('open-recordings')">查看录像</el-button>
          <el-button v-if="activeTask.status === 'failed' || activeTask.status === 'retry_wait'" type="warning" @click="retry(activeTask)">重新上传</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.upload-page{max-width:1760px;margin:0 auto;padding:20px 24px 30px}.provider-panel{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;padding:16px 18px;margin-bottom:12px;border:1px solid var(--nvr-border);border-radius:10px;background:linear-gradient(145deg,rgba(76,141,255,.08),var(--nvr-surface) 55%)}.provider-main{display:flex;align-items:center;gap:13px}.provider-icon{flex:0 0 38px;width:38px;height:38px;display:grid;place-items:center;border-radius:10px;color:var(--nvr-blue);background:rgba(76,141,255,.11)}.provider-icon :deep(svg){width:20px}.provider-main>div{display:flex;flex-direction:column;gap:5px}.provider-main strong{font-size:14px}.provider-main span{color:var(--nvr-muted);font-size:11px}.provider-state{display:flex;align-items:center;gap:9px}.provider-meta{grid-column:1/-1;display:flex;gap:22px;padding-top:12px;border-top:1px solid var(--nvr-border);color:var(--nvr-muted);font-size:10px;flex-wrap:wrap}.provider-meta span{display:flex;gap:7px}.provider-meta b{color:#9aa7b7;font-weight:600}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:12px}.summary-card{height:82px;display:flex;align-items:center;gap:13px;padding:0 16px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.summary-card>span{width:32px;height:32px;display:grid;place-items:center;border-radius:8px;color:var(--nvr-blue);background:rgba(76,141,255,.09)}.summary-card.danger>span{color:var(--nvr-red);background:rgba(240,93,94,.09)}.summary-card>span :deep(svg){width:16px}.summary-card>div{display:flex;flex-direction:column;gap:5px}.summary-card small{color:var(--nvr-muted);font-size:10px}.summary-card strong{font-size:24px;line-height:1}.panel{border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.toolbar-panel{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:12px;margin-bottom:12px}.toolbar-left,.toolbar-actions{display:flex;align-items:center;gap:8px}.toolbar-actions{color:var(--nvr-muted);font-size:11px}.stream-state{display:inline-flex;align-items:center;gap:5px;color:var(--nvr-yellow)}.stream-state i{width:6px;height:6px;border-radius:50%;background:currentColor}.stream-state.live{color:var(--nvr-green)}.search-box{width:min(460px,36vw)}.status-select{width:150px}.table-panel{overflow:hidden}.recording-cell{display:flex;flex-direction:column;gap:4px;min-width:0}.recording-cell strong{font-size:12px}.recording-cell span,.muted{overflow:hidden;color:var(--nvr-muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.path-cell{color:#9aa7b7;font-size:10px;word-break:break-all}.error-text{color:var(--nvr-red);font-size:10px}.button-icon{width:13px;margin-right:3px}.drawer-head{display:flex;align-items:center;justify-content:space-between;padding-bottom:14px;border-bottom:1px solid var(--nvr-border)}.detail-list{margin:0;border-top:1px solid var(--nvr-border)}.detail-list>div{display:grid;grid-template-columns:105px minmax(0,1fr);gap:12px;padding:11px 0;border-bottom:1px solid var(--nvr-border)}.detail-list dt{color:var(--nvr-muted);font-size:11px}.detail-list dd{margin:0;font-size:11px;word-break:break-all}.error-row dd{color:var(--nvr-red)}.drawer-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}@media(max-width:1000px){.summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.toolbar-panel{align-items:stretch;flex-direction:column}.toolbar-left,.toolbar-actions{flex-wrap:wrap}.search-box{flex:1;width:auto;min-width:240px}}@media(max-width:650px){.upload-page{padding:14px}.provider-panel{grid-template-columns:1fr}.provider-state{justify-content:flex-start}.summary-grid{grid-template-columns:1fr}.toolbar-left{flex-direction:column;align-items:stretch}.search-box,.status-select{width:100%}}
</style>
