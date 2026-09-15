<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { formatDateTime } from './utils/dateTime'

interface LogEntry {
  name: string
  size_bytes: number
  modified_at: string
}

interface LogPolicy {
  camera_log_strategy: 'size'
  camera_log_max_bytes: number
  camera_log_backups: number
  deploy_log_strategy: 'truncate_each_deploy'
}

interface AuditEvent {
  id: number
  code: string
  message: string
  created_at: string
}

interface SystemStatus {
  recorders?: Array<{ state?: string; pid?: number | null }>
  connectivity_monitor?: {
    running?: boolean
    last_cycle_at?: string | null
    error_count?: number
    last_error?: string | null
  }
  storage?: {
    used_bytes?: number
    total_bytes?: number
    used_percent?: number
    state?: string
  }
  upload?: {
    active?: boolean
    configured?: boolean
  }
}

const loading = ref(false)
const status = ref<SystemStatus | null>(null)
const logs = ref<LogEntry[]>([])
const logPolicy = ref<LogPolicy | null>(null)
const audits = ref<AuditEvent[]>([])
const selectedLog = ref<LogEntry | null>(null)
const logContent = ref('')
const logLoading = ref(false)
const restoring = ref(false)
const restoreInput = ref<HTMLInputElement | null>(null)

const runningRecorders = computed(() =>
  status.value?.recorders?.filter((item) => item.state === 'RECORDING' && item.pid != null).length ?? 0,
)
const monitorState = computed(() => {
  const monitor = status.value?.connectivity_monitor
  if (!monitor?.running) return '未运行'
  if ((monitor.error_count ?? 0) > 0) return '有异常记录'
  return '运行正常'
})
const storageLabel = computed(() => {
  const used = status.value?.storage?.used_percent
  return typeof used === 'number' ? `${used.toFixed(1)}%` : '—'
})
const logPolicyLabel = computed(() => {
  if (!logPolicy.value) return ''
  return `摄像头日志 ${formatBytes(logPolicy.value.camera_log_max_bytes)} 轮转，保留 ${logPolicy.value.camera_log_backups} 份历史；部署日志每次部署重置`
})

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const order = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** order).toFixed(order === 0 ? 0 : 1)} ${units[order]}`
}

function formatTime(value?: string | null) {
  return value ? formatDateTime(value) : '尚无记录'
}

async function loadStatus() {
  const { data } = await axios.get<SystemStatus>('/api/system/status')
  status.value = data
}

async function loadLogs() {
  const { data } = await axios.get<LogEntry[]>('/api/operations/logs')
  logs.value = data
  if (selectedLog.value && !data.some((item) => item.name === selectedLog.value?.name)) {
    selectedLog.value = null
    logContent.value = ''
  }
}

async function loadLogPolicy() {
  const { data } = await axios.get<LogPolicy>('/api/operations/log-policy')
  logPolicy.value = data
}

async function loadAudit() {
  const { data } = await axios.get<AuditEvent[]>('/api/operations/audit', { params: { limit: 50 } })
  audits.value = data
}

async function refreshAll() {
  loading.value = true
  try {
    await Promise.all([loadStatus(), loadLogs(), loadLogPolicy(), loadAudit()])
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '加载运维信息失败')
  } finally {
    loading.value = false
  }
}

async function openLog(log: LogEntry) {
  selectedLog.value = log
  logLoading.value = true
  try {
    const { data } = await axios.get<{ name: string; content: string }>(
      `/api/operations/logs/${encodeURIComponent(log.name)}`,
      { params: { tail_lines: 400 } },
    )
    logContent.value = data.content
  } catch (error) {
    logContent.value = ''
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '读取日志失败')
  } finally {
    logLoading.value = false
  }
}

function downloadLogUrl(log: LogEntry) {
  return `/api/operations/logs/${encodeURIComponent(log.name)}/download`
}

async function exportBackup() {
  try {
    const { data } = await axios.get('/api/operations/backup')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    const date = new Date().toISOString().slice(0, 10)
    anchor.href = url
    anchor.download = `camera-recorder-config-${date}.json`
    anchor.click()
    URL.revokeObjectURL(url)
    await loadAudit()
    ElMessage.success('脱敏配置备份已导出')
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '导出备份失败')
  }
}

function chooseRestoreFile() {
  restoreInput.value?.click()
}

async function restoreBackup(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  restoring.value = true
  try {
    const payload = JSON.parse(await file.text())
    await ElMessageBox.confirm(
      '将恢复系统、通知和现有同名摄像头的非敏感配置。现有密码不会被覆盖，备份中不存在的摄像头不会自动创建。',
      '恢复配置备份',
      { confirmButtonText: '确认恢复', cancelButtonText: '取消', type: 'warning' },
    )
    const { data } = await axios.post<{
      restored_cameras: number
      skipped_cameras: string[]
    }>('/api/operations/restore', payload)
    const suffix = data.skipped_cameras.length ? `，跳过 ${data.skipped_cameras.length} 台缺少本地凭据的设备` : ''
    ElMessage.success(`配置已恢复，更新 ${data.restored_cameras} 台摄像头${suffix}`)
    await refreshAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (error instanceof SyntaxError) {
      ElMessage.error('备份文件不是有效的 JSON')
    } else {
      ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '恢复备份失败')
    }
  } finally {
    input.value = ''
    restoring.value = false
  }
}

onMounted(() => { void refreshAll() })
</script>

<template>
  <section class="operations-page" v-loading="loading">
    <header class="operations-header">
      <div>
        <span class="eyebrow">OPERATIONS</span>
        <h2>运维工具</h2>
        <p>查看运行状态与日志，导出脱敏配置，并为外部监控系统提供基础指标。</p>
      </div>
      <div class="header-actions">
        <a class="metrics-link" href="/metrics" target="_blank" rel="noopener noreferrer">Prometheus 指标</a>
        <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
      </div>
    </header>

    <div class="status-grid">
      <article class="status-card">
        <span>录像进程</span>
        <strong>{{ runningRecorders }}</strong>
        <small>当前运行 Recorder</small>
      </article>
      <article class="status-card">
        <span>连接监控</span>
        <strong>{{ monitorState }}</strong>
        <small>最近轮询 {{ formatTime(status?.connectivity_monitor?.last_cycle_at) }}</small>
      </article>
      <article class="status-card">
        <span>录像盘使用率</span>
        <strong>{{ storageLabel }}</strong>
        <small>{{ status?.storage?.state || '状态未知' }}</small>
      </article>
      <article class="status-card">
        <span>归档服务</span>
        <strong>{{ status?.upload?.active ? '已启用' : status?.upload?.configured ? '待启用' : '未配置' }}</strong>
        <small>OpenList / WebDAV</small>
      </article>
    </div>

    <div class="operations-grid">
      <article class="operation-card log-panel">
        <div class="card-heading">
          <div>
            <h3>运行日志</h3>
            <p>仅显示服务日志目录中的直属文件，不递归访问其他路径。</p>
            <p v-if="logPolicyLabel" class="log-policy-note">{{ logPolicyLabel }}</p>
          </div>
          <span>{{ logs.length }} 个文件</span>
        </div>
        <div class="log-layout">
          <div class="log-list">
            <button
              v-for="log in logs"
              :key="log.name"
              type="button"
              :class="{ active: selectedLog?.name === log.name }"
              @click="openLog(log)"
            >
              <span><strong>{{ log.name }}</strong><small>{{ formatBytes(log.size_bytes) }} · {{ formatTime(log.modified_at) }}</small></span>
              <a :href="downloadLogUrl(log)" download title="下载日志" @click.stop><Download /></a>
            </button>
            <div v-if="!logs.length" class="empty-line">暂无可读取日志</div>
          </div>
          <div class="log-preview" :class="{ loading: logLoading }">
            <div class="preview-title">
              <span>{{ selectedLog?.name || '选择日志文件' }}</span>
              <small>{{ selectedLog ? '最近 400 行' : '不会自动读取文件内容' }}</small>
            </div>
            <pre>{{ logContent || (selectedLog ? '日志为空' : '从左侧选择一个日志文件查看。') }}</pre>
          </div>
        </div>
      </article>

      <div class="side-stack">
        <article class="operation-card backup-card">
          <div class="card-heading"><div><h3>配置备份</h3><p>只导出可恢复的非敏感配置。</p></div></div>
          <div class="security-note">
            摄像头、WebDAV 与 SMTP 密码不会写入备份；恢复时也不会清空或覆盖现有密钥。
          </div>
          <div class="backup-actions">
            <el-button type="primary" :icon="Download" @click="exportBackup">导出 JSON</el-button>
            <el-button :icon="UploadFilled" :loading="restoring" @click="chooseRestoreFile">恢复备份</el-button>
            <input ref="restoreInput" class="hidden-file" type="file" accept="application/json,.json" @change="restoreBackup">
          </div>
        </article>

        <article class="operation-card audit-card">
          <div class="card-heading"><div><h3>操作审计</h3><p>复用系统 Event 记录关键运维动作。</p></div></div>
          <div class="audit-list">
            <div v-for="item in audits" :key="item.id" class="audit-row">
              <span class="audit-dot" />
              <div><strong>{{ item.message }}</strong><small>{{ formatTime(item.created_at) }} · {{ item.code }}</small></div>
            </div>
            <div v-if="!audits.length" class="empty-line">暂无运维操作记录</div>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.operations-page{width:min(1380px,100%);margin:0 auto;padding:18px 22px 28px;box-sizing:border-box;color:var(--nvr-text)}
.operations-header{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:12px}.operations-header h2{margin:3px 0 4px;font-size:18px;font-weight:650;letter-spacing:-.02em}.operations-header p,.card-heading p{margin:0;color:var(--nvr-muted);font-size:11px}.eyebrow{color:var(--nvr-subtle);font-size:9px;font-weight:700;letter-spacing:.12em}.header-actions{display:flex;align-items:center;gap:6px}.metrics-link{display:inline-flex;align-items:center;height:30px;padding:0 10px;border:1px solid var(--nvr-border);border-radius:7px;color:var(--nvr-text-soft);font-size:11px;text-decoration:none;background:var(--nvr-surface)}.metrics-link:hover{border-color:var(--nvr-blue);color:var(--nvr-text)}
.status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:10px}.status-card,.operation-card{border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface)}.status-card{display:flex;min-height:78px;flex-direction:column;justify-content:center;padding:10px 12px}.status-card>span{color:var(--nvr-muted);font-size:10px}.status-card strong{margin:4px 0 2px;font-size:15px;font-weight:620}.status-card small{overflow:hidden;color:var(--nvr-subtle);font-size:9px;text-overflow:ellipsis;white-space:nowrap}
.operations-grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(300px,.8fr);gap:10px}.operation-card{min-width:0;padding:12px}.card-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px}.card-heading h3{margin:0 0 3px;font-size:12px;font-weight:650}.card-heading>span{color:var(--nvr-subtle);font-size:9px}.log-policy-note{margin-top:4px!important;color:var(--nvr-subtle)!important;font-size:9px!important}.log-layout{display:grid;grid-template-columns:230px minmax(0,1fr);min-height:420px;overflow:hidden;border:1px solid var(--nvr-border);border-radius:8px}.log-list{overflow:auto;border-right:1px solid var(--nvr-border);background:color-mix(in srgb,var(--nvr-surface) 88%,var(--nvr-bg))}.log-list>button{display:flex;width:100%;align-items:center;justify-content:space-between;gap:8px;padding:9px 10px;border:0;border-bottom:1px solid color-mix(in srgb,var(--nvr-border) 72%,transparent);background:transparent;color:var(--nvr-text);text-align:left;cursor:pointer}.log-list>button:hover,.log-list>button.active{background:var(--nvr-hover)}.log-list>button>span{display:flex;min-width:0;flex-direction:column;gap:2px}.log-list strong{overflow:hidden;font-size:10px;font-weight:580;text-overflow:ellipsis;white-space:nowrap}.log-list small{color:var(--nvr-subtle);font-size:8px}.log-list a{display:grid;width:24px;height:24px;flex:0 0 24px;place-items:center;border-radius:6px;color:var(--nvr-muted)}.log-list a:hover{background:var(--nvr-surface);color:var(--nvr-text)}.log-list a svg{width:13px}.log-preview{display:flex;min-width:0;flex-direction:column;background:#090b0e}.preview-title{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.08);color:#d8dde6;font-size:10px}.preview-title small{color:#737b88;font-size:8px}.log-preview pre{min-height:0;flex:1;overflow:auto;margin:0;padding:10px;color:#adb5c0;font:10px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word}.log-preview.loading{opacity:.65}
.side-stack{display:flex;min-width:0;flex-direction:column;gap:10px}.security-note{margin:8px 0 12px;padding:9px 10px;border-left:2px solid var(--nvr-blue);background:color-mix(in srgb,var(--nvr-blue) 7%,transparent);color:var(--nvr-muted);font-size:10px;line-height:1.55}.backup-actions{display:flex;flex-wrap:wrap;gap:6px}.hidden-file{display:none}.audit-card{min-height:0;flex:1}.audit-list{max-height:330px;overflow:auto}.audit-row{display:grid;grid-template-columns:8px minmax(0,1fr);gap:7px;padding:8px 2px;border-bottom:1px solid color-mix(in srgb,var(--nvr-border) 72%,transparent)}.audit-dot{width:5px;height:5px;margin-top:5px;border-radius:50%;background:var(--nvr-blue)}.audit-row>div{display:flex;min-width:0;flex-direction:column;gap:2px}.audit-row strong{font-size:10px;font-weight:550}.audit-row small{color:var(--nvr-subtle);font-size:8px}.empty-line{padding:18px 10px;color:var(--nvr-subtle);font-size:10px;text-align:center}
@media(max-width:1050px){.status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.operations-grid{grid-template-columns:1fr}.side-stack{display:grid;grid-template-columns:1fr 1fr}.audit-list{max-height:250px}}
@media(max-width:720px){.operations-page{padding:14px}.operations-header{align-items:flex-start;flex-direction:column}.header-actions{width:100%}.status-grid{grid-template-columns:1fr 1fr}.log-layout{grid-template-columns:1fr;min-height:0}.log-list{max-height:210px;border-right:0;border-bottom:1px solid var(--nvr-border)}.log-preview{min-height:300px}.side-stack{grid-template-columns:1fr}}
</style>
