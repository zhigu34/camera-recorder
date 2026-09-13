<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { Download, Refresh, VideoCamera } from '@element-plus/icons-vue'

import type { ExportArtifact, ExportJob, ExportStatus } from './types/exports'

const props = defineProps<{
  modelValue: boolean
  cameraId: number | null
  cameraName?: string
  date?: string
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
}>()

const router = useRouter()
const loading = ref(false)
const jobs = ref<ExportJob[]>([])
const artifactsByJob = ref<Record<number, ExportArtifact[]>>({})
const errorMessage = ref('')
let refreshTimer: ReturnType<typeof setTimeout> | null = null

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const activeJobs = computed(() => jobs.value.filter((job) => job.status === 'pending' || job.status === 'processing'))

function clearRefreshTimer() {
  if (refreshTimer !== null) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

function scheduleRefresh() {
  clearRefreshTimer()
  if (!visible.value || !activeJobs.value.length) return
  refreshTimer = setTimeout(() => void loadHistory(true), 1800)
}

function statusLabel(status: ExportStatus) {
  if (status === 'pending') return '等待中'
  if (status === 'processing') return '处理中'
  if (status === 'ready') return '可下载'
  if (status === 'failed') return '失败'
  return '已过期'
}

function statusType(status: ExportStatus): 'primary' | 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'ready') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'pending' || status === 'processing') return 'primary'
  return 'info'
}

function localClock(value?: string | null) {
  const match = value?.match(/T(\d{2}:\d{2}:\d{2})/)
  return match?.[1] || '--:--:--'
}

function localDate(value?: string | null) {
  return value && value.length >= 10 ? value.slice(0, 10) : '-'
}

function formatRange(job: ExportJob) {
  return `${localDate(job.requested_start_at)} ${localClock(job.requested_start_at)} – ${localClock(job.requested_end_at)}`
}

function formatDuration(seconds?: number | null) {
  const value = Math.max(0, Math.round(Number(seconds || 0)))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = value % 60
  if (hours) return `${hours}h ${minutes}m`
  if (minutes) return `${minutes}m ${secs}s`
  return `${secs}s`
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

function modeLabel(job: ExportJob) {
  const mode = job.export_mode === 'exact' ? '精确' : '快速'
  if (job.gap_policy === 'merge') return `${mode} · 合并`
  return `${mode} · 分段${job.package_mode === 'zip' ? ' · ZIP' : ''}`
}

async function loadArtifacts(jobId: number) {
  const { data } = await axios.get<ExportArtifact[]>(`/api/exports/${jobId}/artifacts`)
  artifactsByJob.value = { ...artifactsByJob.value, [jobId]: data }
}

async function loadHistory(silent = false) {
  if (!props.cameraId) {
    jobs.value = []
    artifactsByJob.value = {}
    return
  }
  if (!silent) loading.value = true
  errorMessage.value = ''
  try {
    const { data } = await axios.get<ExportJob[]>('/api/exports', {
      params: { camera_id: props.cameraId, limit: 20 },
    })
    jobs.value = data
    const readyIds = data.filter((job) => job.status === 'ready').map((job) => job.id)
    const nextArtifacts: Record<number, ExportArtifact[]> = {}
    await Promise.all(readyIds.map(async (jobId) => {
      const response = await axios.get<ExportArtifact[]>(`/api/exports/${jobId}/artifacts`)
      nextArtifacts[jobId] = response.data
    }))
    artifactsByJob.value = nextArtifacts
  } catch (error) {
    errorMessage.value = axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '导出记录加载失败'
  } finally {
    loading.value = false
    scheduleRefresh()
  }
}

function downloadArtifact(job: ExportJob, artifact: ExportArtifact) {
  const url = `/api/exports/${job.id}/artifacts/${artifact.id}/download`
  window.open(url, '_blank', 'noopener,noreferrer')
}

function openNewExport() {
  if (!props.cameraId) return
  visible.value = false
  void router.push({
    path: '/recordings/playback',
    query: {
      camera_id: String(props.cameraId),
      ...(props.date ? { date: props.date } : {}),
    },
  })
}

watch(
  () => [props.modelValue, props.cameraId] as const,
  ([isVisible]) => {
    clearRefreshTimer()
    if (isVisible) void loadHistory()
  },
  { immediate: true },
)

onBeforeUnmount(clearRefreshTimer)
</script>

<template>
  <el-drawer v-model="visible" size="540px" class="recording-export-history-drawer" destroy-on-close>
    <template #header>
      <div class="export-history-title">
        <div>
          <strong>导出记录</strong>
          <span>{{ cameraName || (cameraId ? `摄像头 #${cameraId}` : '选择摄像头') }}</span>
        </div>
        <el-tag v-if="activeJobs.length" size="small" type="primary">{{ activeJobs.length }} 个处理中</el-tag>
      </div>
    </template>

    <div class="export-history-body" v-loading="loading">
      <div class="export-history-toolbar">
        <div>
          <strong>最近 20 个任务</strong>
          <span>导出文件默认保留 24 小时。</span>
        </div>
        <div class="export-history-toolbar-actions">
          <el-button size="small" :icon="Refresh" :loading="loading" @click="loadHistory()">刷新</el-button>
          <el-button size="small" type="primary" :icon="VideoCamera" :disabled="!cameraId" @click="openNewExport">导出新片段</el-button>
        </div>
      </div>

      <div v-if="errorMessage" class="export-history-error">{{ errorMessage }}</div>

      <div v-if="!loading && !jobs.length && !errorMessage" class="export-history-empty">
        <VideoCamera />
        <strong>还没有导出记录</strong>
        <span>从回放时间轴选择范围后即可创建导出任务。</span>
        <el-button type="primary" size="small" :disabled="!cameraId" @click="openNewExport">去回放导出</el-button>
      </div>

      <div v-else class="export-history-list">
        <article v-for="job in jobs" :key="job.id" class="export-history-card">
          <div class="export-history-card-head">
            <div>
              <strong>{{ formatRange(job) }}</strong>
              <span>#{{ job.id }} · {{ modeLabel(job) }} · {{ formatDuration(job.covered_duration) }}</span>
            </div>
            <el-tag size="small" :type="statusType(job.status)">{{ statusLabel(job.status) }}</el-tag>
          </div>

          <el-progress
            v-if="job.status === 'pending' || job.status === 'processing'"
            :percentage="Math.max(0, Math.min(100, Math.round(job.progress)))"
            :stroke-width="5"
            :show-text="false"
          />

          <div class="export-history-meta">
            <span>缺口 {{ job.gap_count }}</span>
            <span>请求 {{ formatDuration(job.requested_duration) }}</span>
            <span v-if="job.expires_at">到期 {{ localDate(job.expires_at) }} {{ localClock(job.expires_at) }}</span>
          </div>

          <div v-if="job.status === 'ready'" class="export-history-artifacts">
            <button
              v-for="artifact in artifactsByJob[job.id] || []"
              :key="artifact.id"
              type="button"
              @click="downloadArtifact(job, artifact)"
            >
              <Download />
              <span>{{ artifact.kind === 'zip' ? '下载 ZIP' : artifact.segment_index ? `下载片段 ${artifact.segment_index}` : '下载 MP4' }}</span>
              <small>{{ formatBytes(artifact.file_size) }}</small>
            </button>
            <span v-if="!(artifactsByJob[job.id] || []).length" class="export-history-muted">产物正在同步，可刷新重试。</span>
          </div>

          <div v-else-if="job.status === 'failed'" class="export-history-failure">{{ job.error_message || '导出失败' }}</div>
          <div v-else-if="job.status === 'expired'" class="export-history-muted">导出文件已过期，可回到回放页重新生成。</div>
        </article>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.export-history-title{width:100%;display:flex;align-items:center;justify-content:space-between;gap:12px;padding-right:8px}.export-history-title>div{min-width:0;display:grid;gap:3px}.export-history-title strong{color:var(--nvr-text);font-size:15px}.export-history-title span{overflow:hidden;color:var(--nvr-muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.export-history-body{min-height:220px;display:grid;align-content:start;gap:10px}.export-history-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 11px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.export-history-toolbar>div:first-child{display:grid;gap:2px}.export-history-toolbar strong{font-size:11px}.export-history-toolbar span{color:var(--nvr-muted);font-size:9px}.export-history-toolbar-actions{display:flex;gap:6px}.export-history-error,.export-history-failure{padding:8px 10px;border:1px solid color-mix(in srgb,var(--nvr-red) 34%,var(--nvr-border));border-radius:7px;color:var(--nvr-red);background:color-mix(in srgb,var(--nvr-red) 7%,var(--nvr-surface));font-size:10px}.export-history-empty{min-height:240px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px dashed var(--nvr-border-strong);border-radius:9px;color:var(--nvr-muted);text-align:center}.export-history-empty :deep(svg){width:32px;margin-bottom:9px;color:var(--nvr-subtle)}.export-history-empty strong{color:var(--nvr-text-soft);font-size:12px}.export-history-empty span{margin:4px 0 12px;font-size:10px}.export-history-list{display:grid;gap:8px}.export-history-card{display:grid;gap:8px;padding:11px 12px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.export-history-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.export-history-card-head>div{min-width:0;display:grid;gap:3px}.export-history-card-head strong{color:var(--nvr-text-soft);font-size:11px;font-variant-numeric:tabular-nums}.export-history-card-head span{color:var(--nvr-muted);font-size:9px}.export-history-meta{display:flex;flex-wrap:wrap;gap:8px;color:var(--nvr-subtle);font-size:9px}.export-history-artifacts{display:flex;flex-wrap:wrap;gap:6px}.export-history-artifacts button{display:flex;align-items:center;gap:5px;padding:6px 8px;border:1px solid var(--nvr-border);border-radius:6px;background:var(--nvr-input);color:var(--nvr-text-soft);font:inherit;cursor:pointer}.export-history-artifacts button:hover{border-color:color-mix(in srgb,var(--nvr-blue) 52%,var(--nvr-border))}.export-history-artifacts button :deep(svg){width:12px}.export-history-artifacts button span{font-size:9px}.export-history-artifacts button small{color:var(--nvr-subtle);font-size:8px}.export-history-muted{color:var(--nvr-muted);font-size:9px}
@media(max-width:620px){.export-history-toolbar,.export-history-card-head{align-items:stretch;flex-direction:column}.export-history-toolbar-actions{display:grid;grid-template-columns:1fr 1fr}.export-history-toolbar-actions :deep(.el-button){width:100%;margin:0}}
</style>

<style>
.recording-export-history-drawer.el-drawer{width:min(540px,100vw)!important;border-left:1px solid var(--nvr-border-strong);background:var(--nvr-bg)}.recording-export-history-drawer .el-drawer__header{margin:0;padding:14px 16px 12px;border-bottom:1px solid var(--nvr-border);background:var(--nvr-surface)}.recording-export-history-drawer .el-drawer__body{padding:12px 14px 20px;background:var(--nvr-bg)}
</style>
