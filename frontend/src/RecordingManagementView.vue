<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Cloudy, DataLine, Search, VideoPlay, WarningFilled } from '@element-plus/icons-vue'

interface Camera { id: number; name: string; ip: string }
interface Recording {
  id: number
  camera_id: number
  started_at?: string | null
  ended_at?: string | null
  duration?: number | null
  mp4_path: string
  file_size?: number | null
  video_codec?: string | null
  audio_codec?: string | null
  width?: number | null
  height?: number | null
  fps?: number | null
  status: string
  health_status: string
  warning_count: number
  timestamp_warning_count: number
  network_warning_count: number
  upload_status: string
  created_at: string
}
interface UploadStatus { active: boolean; enabled: boolean; configured: boolean }
interface RecordingStats { total: number; total_size: number; archived: number; pending_archive: number; abnormal: number }
interface RecordingPage { items: Recording[]; total: number; offset: number; limit: number; stats: RecordingStats }

const emit = defineEmits<{
  (event: 'open-playback'): void
  (event: 'open-uploads'): void
}>()

const loading = ref(false)
const recordings = ref<Recording[]>([])
const cameras = ref<Camera[]>([])
const uploadStatus = ref<UploadStatus | null>(null)
const stats = ref<RecordingStats>({ total: 0, total_size: 0, archived: 0, pending_archive: 0, abnormal: 0 })
const total = ref(0)
const page = ref(1)
const pageSize = ref(100)
const searchText = ref('')
const cameraFilter = ref<number | null>(null)
const uploadFilter = ref('')
const healthFilter = ref('')
const storageFilter = ref('')
const dateRange = ref<[string, string] | null>(null)
const detailVisible = ref(false)
const activeRecording = ref<Recording | null>(null)
let filterTimer: number | null = null

function cameraName(cameraId: number) { return cameras.value.find((camera) => camera.id === cameraId)?.name || `摄像头 #${cameraId}` }
function fileName(row: Recording) { return row.mp4_path.split('/').pop() || row.mp4_path }
function formatBytes(bytes?: number | null) {
  const value = Number(bytes || 0)
  if (!value) return '-'
  if (value >= 1024 ** 4) return `${(value / 1024 ** 4).toFixed(2)} TB`
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(2)} GB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}
function formatDuration(seconds?: number | null) {
  const value = Math.max(0, Math.round(Number(seconds || 0)))
  if (!value) return '-'
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = value % 60
  if (hours) return `${hours}h ${minutes}m`
  if (minutes) return `${minutes}m ${secs}s`
  return `${secs}s`
}
function formatTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
function storageLabel(row: Recording) {
  if (row.status === 'deleted' && row.upload_status === 'success') return '仅云端'
  if (row.upload_status === 'success') return '本地 + 云端'
  return '本地'
}
function storageType(row: Recording) {
  if (row.status === 'deleted' && row.upload_status === 'success') return 'primary'
  if (row.upload_status === 'success') return 'success'
  return 'info'
}
function uploadLabel(value: string) {
  if (value === 'success') return '已归档'
  if (value === 'uploading') return '上传中'
  if (value === 'retry_wait') return '等待重试'
  if (value === 'failed') return '失败'
  if (value === 'pending') return '待归档'
  return value || '-'
}
function uploadType(value: string) {
  if (value === 'success') return 'success'
  if (value === 'failed') return 'danger'
  if (value === 'uploading') return 'primary'
  if (value === 'retry_wait') return 'warning'
  return 'info'
}
function healthLabel(row: Recording) {
  if (row.health_status === 'healthy' && !row.warning_count) return '正常'
  return row.health_status === 'failed' ? '失败' : `异常 ${row.warning_count || ''}`.trim()
}
function healthType(row: Recording) {
  if (row.health_status === 'healthy' && !row.warning_count) return 'success'
  if (row.health_status === 'failed') return 'danger'
  return 'warning'
}
function clearFilters() {
  searchText.value = ''
  cameraFilter.value = null
  uploadFilter.value = ''
  healthFilter.value = ''
  storageFilter.value = ''
  dateRange.value = null
}
function openDetail(row: Recording) { activeRecording.value = row; detailVisible.value = true }
function requestParams() {
  const params: Record<string, string | number> = {
    offset: (page.value - 1) * pageSize.value,
    limit: pageSize.value,
  }
  if (searchText.value.trim()) params.q = searchText.value.trim()
  if (cameraFilter.value !== null) params.camera_id = cameraFilter.value
  if (uploadFilter.value) params.upload_status = uploadFilter.value
  if (healthFilter.value) params.health = healthFilter.value
  if (storageFilter.value) params.storage = storageFilter.value
  if (dateRange.value) {
    params.date_from = dateRange.value[0]
    params.date_to = dateRange.value[1]
  }
  return params
}
async function loadPage(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const { data } = await axios.get<RecordingPage>('/api/recording-management', { params: requestParams() })
    recordings.value = data.items
    total.value = data.total
    stats.value = data.stats
    if (activeRecording.value) activeRecording.value = data.items.find((item) => item.id === activeRecording.value?.id) || activeRecording.value
  } catch (error) {
    if (showLoading) ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '录像管理加载失败')
  } finally { if (showLoading) loading.value = false }
}
async function loadInitial() {
  loading.value = true
  try {
    const [pageRes, cameraRes, statusRes] = await Promise.all([
      axios.get<RecordingPage>('/api/recording-management', { params: requestParams() }),
      axios.get<Camera[]>('/api/cameras'),
      axios.get<UploadStatus>('/api/uploads'),
    ])
    recordings.value = pageRes.data.items
    total.value = pageRes.data.total
    stats.value = pageRes.data.stats
    cameras.value = cameraRes.data
    uploadStatus.value = statusRes.data
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '录像管理加载失败')
  } finally { loading.value = false }
}
function scheduleFilterLoad() {
  page.value = 1
  if (filterTimer !== null) window.clearTimeout(filterTimer)
  filterTimer = window.setTimeout(() => { filterTimer = null; void loadPage(false) }, 250)
}
function changePage(value: number) { page.value = value; void loadPage() }

watch([searchText, cameraFilter, uploadFilter, healthFilter, storageFilter, dateRange], scheduleFilterLoad)
onMounted(loadInitial)
onBeforeUnmount(() => { if (filterTimer !== null) window.clearTimeout(filterTimer) })
</script>

<template>
  <div class="recording-page" v-loading="loading">
    <section class="summary-grid">
      <article class="summary-card"><span class="summary-icon"><DataLine /></span><div><small>录像文件</small><strong>{{ stats.total }}</strong><em>{{ formatBytes(stats.total_size) }}</em></div></article>
      <article class="summary-card"><span class="summary-icon"><Cloudy /></span><div><small>已归档</small><strong>{{ stats.archived }}</strong><em>{{ uploadStatus?.active ? '自动归档运行中' : '自动归档未运行' }}</em></div></article>
      <article class="summary-card"><span class="summary-icon"><Cloudy /></span><div><small>待处理归档</small><strong>{{ stats.pending_archive }}</strong><em>详细任务统一在上传管理处理</em></div></article>
      <article class="summary-card" :class="{ danger: stats.abnormal > 0 }"><span class="summary-icon"><WarningFilled /></span><div><small>异常录像</small><strong>{{ stats.abnormal }}</strong><em>健康检查或时间戳告警</em></div></article>
    </section>

    <section class="panel filter-panel">
      <div class="filter-row">
        <el-input v-model="searchText" clearable placeholder="搜索摄像头、IP、文件名或路径" class="search-box"><template #prefix><Search /></template></el-input>
        <el-select v-model="cameraFilter" clearable placeholder="全部摄像头" class="select-box"><el-option v-for="camera in cameras" :key="camera.id" :label="camera.name" :value="camera.id" /></el-select>
        <el-select v-model="storageFilter" clearable placeholder="存储位置" class="select-box"><el-option label="本地可用" value="local" /><el-option label="仅云端" value="cloud" /></el-select>
        <el-select v-model="uploadFilter" clearable placeholder="归档状态" class="select-box"><el-option label="待归档" value="pending" /><el-option label="上传中" value="uploading" /><el-option label="等待重试" value="retry_wait" /><el-option label="已归档" value="success" /><el-option label="失败" value="failed" /></el-select>
        <el-select v-model="healthFilter" clearable placeholder="健康状态" class="select-box"><el-option label="正常" value="healthy" /><el-option label="异常" value="abnormal" /></el-select>
        <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" unlink-panels class="date-range" />
      </div>
      <div class="filter-actions"><span>共 {{ total }} 条 · 当前第 {{ page }} 页</span><el-button link @click="clearFilters">清除筛选</el-button><el-button @click="loadPage()">刷新</el-button><el-button type="primary" plain @click="emit('open-uploads')">上传管理</el-button></div>
    </section>

    <section class="panel table-panel">
      <el-table :data="recordings" height="calc(100vh - 390px)" empty-text="没有符合条件的录像">
        <el-table-column label="录像" min-width="250" fixed="left"><template #default="{ row }"><div class="recording-cell"><strong>{{ cameraName(row.camera_id) }}</strong><span>{{ fileName(row) }}</span></div></template></el-table-column>
        <el-table-column label="开始时间" min-width="175"><template #default="{ row }">{{ formatTime(row.started_at) }}</template></el-table-column>
        <el-table-column label="时长" width="100"><template #default="{ row }">{{ formatDuration(row.duration) }}</template></el-table-column>
        <el-table-column label="大小" width="105"><template #default="{ row }">{{ formatBytes(row.file_size) }}</template></el-table-column>
        <el-table-column label="视频" width="145"><template #default="{ row }"><span class="muted">{{ row.video_codec || '-' }} · {{ row.width || '-' }}×{{ row.height || '-' }}</span></template></el-table-column>
        <el-table-column label="存储" width="125"><template #default="{ row }"><el-tag :type="storageType(row)" size="small">{{ storageLabel(row) }}</el-tag></template></el-table-column>
        <el-table-column label="归档" width="120"><template #default="{ row }"><el-tag :type="uploadType(row.upload_status)" size="small">{{ uploadLabel(row.upload_status) }}</el-tag></template></el-table-column>
        <el-table-column label="健康" width="110"><template #default="{ row }"><el-tag :type="healthType(row)" size="small">{{ healthLabel(row) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="210" fixed="right"><template #default="{ row }"><el-button size="small" @click="openDetail(row)">详情</el-button><el-button size="small" type="primary" plain @click="emit('open-playback')"><VideoPlay class="button-icon" />回放</el-button><el-button v-if="row.upload_status === 'failed' || row.upload_status === 'retry_wait'" size="small" type="warning" plain @click="emit('open-uploads')">处理归档</el-button></template></el-table-column>
      </el-table>
      <div class="pagination-row"><el-pagination background layout="prev, pager, next" :current-page="page" :page-size="pageSize" :total="total" :pager-count="7" @current-change="changePage" /></div>
    </section>

    <el-drawer v-model="detailVisible" title="录像详情" size="460px">
      <template v-if="activeRecording">
        <div class="detail-title"><strong>{{ cameraName(activeRecording.camera_id) }}</strong><span>{{ fileName(activeRecording) }}</span></div>
        <div class="detail-tags"><el-tag :type="storageType(activeRecording)">{{ storageLabel(activeRecording) }}</el-tag><el-tag :type="uploadType(activeRecording.upload_status)">{{ uploadLabel(activeRecording.upload_status) }}</el-tag><el-tag :type="healthType(activeRecording)">{{ healthLabel(activeRecording) }}</el-tag></div>
        <dl class="detail-list"><div><dt>开始时间</dt><dd>{{ formatTime(activeRecording.started_at) }}</dd></div><div><dt>结束时间</dt><dd>{{ formatTime(activeRecording.ended_at) }}</dd></div><div><dt>时长</dt><dd>{{ formatDuration(activeRecording.duration) }}</dd></div><div><dt>文件大小</dt><dd>{{ formatBytes(activeRecording.file_size) }}</dd></div><div><dt>编码</dt><dd>{{ activeRecording.video_codec || '-' }} / {{ activeRecording.audio_codec || '-' }}</dd></div><div><dt>分辨率</dt><dd>{{ activeRecording.width || '-' }} × {{ activeRecording.height || '-' }}</dd></div><div class="wide"><dt>本地路径</dt><dd>{{ activeRecording.mp4_path }}</dd></div><div><dt>归档状态</dt><dd>{{ uploadLabel(activeRecording.upload_status) }}</dd></div><div><dt>告警</dt><dd>{{ activeRecording.warning_count }}（时间戳 {{ activeRecording.timestamp_warning_count }} / 网络 {{ activeRecording.network_warning_count }}）</dd></div></dl>
        <div class="drawer-actions"><el-button @click="emit('open-uploads')">上传管理</el-button><el-button type="primary" @click="emit('open-playback')">进入录像回放</el-button></div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.recording-page{max-width:1760px;margin:0 auto;padding:20px 24px 30px}.summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:12px}.summary-card{min-height:88px;display:flex;align-items:center;gap:13px;padding:14px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.summary-card.danger{border-color:rgba(240,93,94,.24)}.summary-icon{flex:0 0 34px;width:34px;height:34px;display:grid;place-items:center;border-radius:9px;color:var(--nvr-blue);background:rgba(76,141,255,.1)}.summary-card.danger .summary-icon{color:var(--nvr-red);background:rgba(240,93,94,.09)}.summary-icon :deep(svg){width:17px}.summary-card>div{min-width:0;display:grid;grid-template-columns:auto 1fr;align-items:end;column-gap:8px;row-gap:4px}.summary-card small{grid-column:1/-1;color:var(--nvr-muted);font-size:10px}.summary-card strong{font-size:23px;line-height:1;font-weight:680}.summary-card em{overflow:hidden;color:#68788c;font-size:9px;font-style:normal;text-overflow:ellipsis;white-space:nowrap}.panel{border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.filter-panel{padding:11px;margin-bottom:12px}.filter-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.search-box{flex:1;min-width:260px}.select-box{width:145px}.date-range{width:235px!important}.filter-actions{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:9px;color:var(--nvr-muted);font-size:10px}.table-panel{overflow:hidden}.recording-cell{display:flex;flex-direction:column;gap:4px;min-width:0}.recording-cell strong{font-size:12px}.recording-cell span{overflow:hidden;color:var(--nvr-muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.muted{color:var(--nvr-muted);font-size:11px}.button-icon{width:13px;margin-right:3px}.pagination-row{display:flex;justify-content:flex-end;padding:10px 12px;border-top:1px solid var(--nvr-border);background:#111820}.detail-title{display:flex;flex-direction:column;gap:5px;padding-bottom:14px;border-bottom:1px solid var(--nvr-border)}.detail-title strong{font-size:16px}.detail-title span{color:var(--nvr-muted);font-size:11px;word-break:break-all}.detail-tags{display:flex;gap:8px;margin:14px 0}.detail-list{margin:0;border-top:1px solid var(--nvr-border)}.detail-list>div{display:grid;grid-template-columns:110px minmax(0,1fr);gap:12px;padding:10px 0;border-bottom:1px solid var(--nvr-border)}.detail-list dt{color:var(--nvr-muted);font-size:11px}.detail-list dd{margin:0;font-size:11px;word-break:break-all}.drawer-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}@media(max-width:1100px){.summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){.recording-page{padding:14px}.summary-grid{grid-template-columns:1fr}.search-box,.select-box,.date-range{width:100%!important}.filter-actions{justify-content:flex-start;flex-wrap:wrap}.pagination-row{justify-content:center}}
</style>
