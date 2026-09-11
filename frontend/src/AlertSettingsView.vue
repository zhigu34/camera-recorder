<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Bell, CircleCheckFilled, Message, Monitor, WarningFilled } from '@element-plus/icons-vue'

interface EmailSettings {
  email_enabled: boolean
  offline_alert_seconds: number
  recovery_stable_seconds: number
  notify_recovery: boolean
  smtp_host: string
  smtp_port: number
  smtp_username: string
  smtp_password_set: boolean
  smtp_from: string
  smtp_to: string
  smtp_use_ssl: boolean
  smtp_starttls: boolean
  smtp_timeout_seconds: number
  configured: boolean
}

interface SystemStatus {
  upload?: { enabled: boolean; configured: boolean; active: boolean }
  storage?: {
    used_percent: number
    state: 'healthy' | 'warning' | 'critical'
    warning_percent: number
    critical_percent: number
  }
  alerts?: {
    monitor?: {
      running: boolean
      last_check_at?: string | null
      last_error?: string | null
      last_event_id?: number
    }
    dispatcher?: {
      active_incidents?: string[]
      active_count?: number
    }
  }
}

const emit = defineEmits<{
  (event: 'open-events'): void
}>()

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const status = ref<SystemStatus | null>(null)
let statusTimer: number | null = null

const form = reactive({
  email_enabled: false,
  offline_alert_seconds: 60,
  recovery_stable_seconds: 10,
  notify_recovery: true,
  smtp_host: '',
  smtp_port: 587,
  smtp_username: '',
  smtp_password: '',
  smtp_password_set: false,
  clear_smtp_password: false,
  smtp_from: '',
  smtp_to: '',
  smtp_use_ssl: false,
  smtp_starttls: true,
  smtp_timeout_seconds: 15,
  configured: false,
})

const monitorRunning = computed(() => Boolean(status.value?.alerts?.monitor?.running))
const activeIncidents = computed(() => status.value?.alerts?.dispatcher?.active_incidents || [])
const alertReady = computed(() => form.email_enabled && form.configured && monitorRunning.value)
const emailStateText = computed(() => {
  if (!form.email_enabled) return '邮件告警已关闭'
  if (!form.configured) return 'SMTP 未配置完整'
  if (!monitorRunning.value) return '告警监控未运行'
  return '邮件告警运行中'
})

const scopeItems = computed(() => [
  {
    title: '摄像头离线',
    detail: `持续离线 ${form.offline_alert_seconds} 秒后发送告警`,
    state: 'camera',
  },
  {
    title: 'FFmpeg 连续失败',
    detail: '录像进程连续失败时发送一次告警，恢复后自动清除事故状态',
    state: 'ffmpeg',
  },
  {
    title: '磁盘空间',
    detail: `warning ${status.value?.storage?.warning_percent ?? '-'}% · critical ${status.value?.storage?.critical_percent ?? '-'}%`,
    state: status.value?.storage?.state || 'unknown',
  },
  {
    title: '上传失败',
    detail: status.value?.upload?.enabled
      ? 'OpenList/WebDAV 上传任务耗尽重试后发送告警'
      : '上传功能关闭时不检查上传失败',
    state: status.value?.upload?.active ? 'active' : 'inactive',
  },
])

function applySettings(data: EmailSettings) {
  Object.assign(form, data, {
    smtp_password: '',
    clear_smtp_password: false,
  })
}

function errorText(error: unknown, fallback: string) {
  return axios.isAxiosError(error) ? error.response?.data?.detail || error.message : fallback
}

async function loadStatus() {
  try {
    const { data } = await axios.get<SystemStatus>('/api/system/status')
    status.value = data
  } catch {
    // Keep the last good status. Manual refresh reports configuration errors separately.
  }
}

async function load() {
  loading.value = true
  try {
    const [settingsRes, statusRes] = await Promise.all([
      axios.get<EmailSettings>('/api/notifications/email'),
      axios.get<SystemStatus>('/api/system/status'),
    ])
    applySettings(settingsRes.data)
    status.value = statusRes.data
  } catch (error) {
    ElMessage.error(errorText(error, '加载告警配置失败'))
  } finally {
    loading.value = false
  }
}

function enableSsl(value: boolean | string | number) {
  if (Boolean(value)) form.smtp_starttls = false
}

function enableStarttls(value: boolean | string | number) {
  if (Boolean(value)) form.smtp_use_ssl = false
}

function passwordChanged() {
  if (form.smtp_password) form.clear_smtp_password = false
}

async function save() {
  saving.value = true
  try {
    const payload = {
      email_enabled: form.email_enabled,
      offline_alert_seconds: form.offline_alert_seconds,
      recovery_stable_seconds: form.recovery_stable_seconds,
      notify_recovery: form.notify_recovery,
      smtp_host: form.smtp_host,
      smtp_port: form.smtp_port,
      smtp_username: form.smtp_username,
      smtp_password: form.smtp_password || null,
      clear_smtp_password: form.clear_smtp_password,
      smtp_from: form.smtp_from,
      smtp_to: form.smtp_to,
      smtp_use_ssl: form.smtp_use_ssl,
      smtp_starttls: form.smtp_starttls,
      smtp_timeout_seconds: form.smtp_timeout_seconds,
    }
    const { data } = await axios.put<EmailSettings>('/api/notifications/email', payload)
    applySettings(data)
    await loadStatus()
    ElMessage.success('告警配置已保存并立即生效')
  } catch (error) {
    ElMessage.error(errorText(error, '保存告警配置失败'))
  } finally {
    saving.value = false
  }
}

async function testEmail() {
  testing.value = true
  try {
    await axios.post('/api/notifications/email/test')
    ElMessage.success('测试邮件已发送，请检查收件箱')
    await loadStatus()
  } catch (error) {
    ElMessage.error(errorText(error, '测试邮件发送失败'))
  } finally {
    testing.value = false
  }
}

function incidentLabel(value: string) {
  if (value === 'storage:critical') return '磁盘空间严重不足'
  if (value === 'storage:cleanup_issue') return '磁盘紧急清理异常'
  if (value === 'upload:failed') return '上传任务持续失败'
  if (value.includes(':ffmpeg_failure_streak')) return `摄像头 FFmpeg 连续失败 · ${value.split(':')[1] || '-'}`
  if (value.startsWith('camera:')) return `摄像头异常 · ${value}`
  return value
}

function lastCheckText() {
  const value = status.value?.alerts?.monitor?.last_check_at
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

onMounted(() => {
  void load()
  statusTimer = window.setInterval(loadStatus, 15000)
})

onBeforeUnmount(() => {
  if (statusTimer !== null) window.clearInterval(statusTimer)
})
</script>

<template>
  <section class="alert-page" v-loading="loading">
    <div class="page-actions">
      <el-button @click="load">刷新</el-button>
      <el-button plain @click="emit('open-events')">查看事件中心</el-button>
      <el-button :loading="testing" @click="testEmail">发送测试邮件</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
    </div>

    <div class="status-grid">
      <article class="status-card" :class="{ good: alertReady, warn: !alertReady }">
        <div class="status-icon"><Message /></div>
        <div><span>邮件告警</span><strong>{{ emailStateText }}</strong></div>
      </article>
      <article class="status-card" :class="{ good: monitorRunning, warn: !monitorRunning }">
        <div class="status-icon"><Monitor /></div>
        <div><span>告警监控器</span><strong>{{ monitorRunning ? '运行中' : '未运行' }}</strong><small>最近检查 {{ lastCheckText() }}</small></div>
      </article>
      <article class="status-card" :class="{ danger: activeIncidents.length > 0, good: activeIncidents.length === 0 }">
        <div class="status-icon"><WarningFilled v-if="activeIncidents.length" /><CircleCheckFilled v-else /></div>
        <div><span>当前事故</span><strong>{{ activeIncidents.length }}</strong><small>{{ activeIncidents.length ? '存在尚未恢复的告警' : '没有活动事故' }}</small></div>
      </article>
      <article class="status-card">
        <div class="status-icon"><Bell /></div>
        <div><span>恢复通知</span><strong>{{ form.notify_recovery ? '已开启' : '已关闭' }}</strong><small>事故恢复后{{ form.notify_recovery ? '发送' : '不发送' }}邮件</small></div>
      </article>
    </div>

    <div class="scope-panel panel">
      <div class="panel-title"><strong>告警范围</strong><span>以下监控项统一受“邮件告警开关”控制，并由后台进行事故去重。</span></div>
      <div class="scope-grid">
        <div v-for="item in scopeItems" :key="item.title" class="scope-item">
          <div class="scope-dot"></div>
          <div><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></div>
        </div>
      </div>
      <div v-if="activeIncidents.length" class="incident-box">
        <strong>活动事故</strong>
        <div class="incident-list">
          <el-tag v-for="incident in activeIncidents" :key="incident" type="danger" effect="dark">{{ incidentLabel(incident) }}</el-tag>
        </div>
      </div>
      <div v-if="status?.alerts?.monitor?.last_error" class="monitor-error">监控器错误：{{ status.alerts.monitor.last_error }}</div>
    </div>

    <div class="settings-layout">
      <div class="panel">
        <div class="panel-title"><strong>告警策略</strong><span>配置离线判定与恢复通知行为。</span></div>
        <el-form label-position="top" class="settings-form">
          <el-form-item label="邮件告警">
            <div class="switch-row"><el-switch v-model="form.email_enabled" /><span>关闭后仍记录事件，但不会发送告警邮件。</span></div>
          </el-form-item>
          <div class="two-cols">
            <el-form-item label="摄像头持续离线多久后告警">
              <el-input-number v-model="form.offline_alert_seconds" :min="0" :max="86400" :step="10" />
              <span class="field-hint">秒；避免短暂网络抖动触发邮件。</span>
            </el-form-item>
            <el-form-item label="恢复稳定时间">
              <el-input-number v-model="form.recovery_stable_seconds" :min="0" :max="3600" :step="5" />
              <span class="field-hint">秒；连续稳定后才判定恢复。</span>
            </el-form-item>
          </div>
          <el-form-item label="恢复邮件">
            <div class="switch-row"><el-switch v-model="form.notify_recovery" /><span>摄像头、磁盘和上传故障恢复后发送恢复通知。</span></div>
          </el-form-item>
        </el-form>
      </div>

      <div class="panel">
        <div class="panel-title"><strong>SMTP</strong><span>SMTP 密码仅加密保存，不会回显。</span></div>
        <el-form label-position="top" class="settings-form">
          <div class="two-cols">
            <el-form-item label="SMTP 服务器"><el-input v-model="form.smtp_host" placeholder="smtp.example.com" /></el-form-item>
            <el-form-item label="端口"><el-input-number v-model="form.smtp_port" :min="1" :max="65535" /></el-form-item>
          </div>
          <el-form-item label="用户名"><el-input v-model="form.smtp_username" autocomplete="off" /></el-form-item>
          <el-form-item label="密码 / 授权码">
            <el-input v-model="form.smtp_password" type="password" show-password autocomplete="new-password" :placeholder="form.smtp_password_set ? '已加密保存；留空保持不变' : '请输入 SMTP 密码或授权码'" @input="passwordChanged" />
            <div v-if="form.smtp_password_set" class="password-row">
              <el-tag size="small" type="success">已加密保存</el-tag>
              <el-checkbox v-model="form.clear_smtp_password">清除已保存密码</el-checkbox>
            </div>
          </el-form-item>
          <div class="two-cols">
            <el-form-item label="发件人"><el-input v-model="form.smtp_from" placeholder="camera@example.com" /></el-form-item>
            <el-form-item label="收件人"><el-input v-model="form.smtp_to" placeholder="ops@example.com,admin@example.com" /><span class="field-hint">多个地址用英文逗号分隔。</span></el-form-item>
          </div>
          <div class="three-cols">
            <el-form-item label="SSL"><el-switch v-model="form.smtp_use_ssl" @change="enableSsl" /><span class="field-hint">常见端口 465</span></el-form-item>
            <el-form-item label="STARTTLS"><el-switch v-model="form.smtp_starttls" @change="enableStarttls" /><span class="field-hint">常见端口 587</span></el-form-item>
            <el-form-item label="连接超时"><el-input-number v-model="form.smtp_timeout_seconds" :min="1" :max="120" /><span class="field-hint">秒</span></el-form-item>
          </div>
        </el-form>
      </div>
    </div>
  </section>
</template>

<style scoped>
.alert-page{padding:18px 20px 28px;color:var(--nvr-text)}.page-actions{display:flex;justify-content:flex-end;gap:8px;margin-bottom:14px;flex-wrap:wrap}.status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px}.status-card{min-height:90px;display:flex;align-items:center;gap:12px;padding:15px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-panel)}.status-icon{flex:0 0 34px;width:34px;height:34px;display:grid;place-items:center;border-radius:9px;color:#8998aa;background:rgba(255,255,255,.045)}.status-icon :deep(svg){width:17px}.status-card>div:last-child{min-width:0;display:flex;flex-direction:column}.status-card span{color:var(--nvr-muted);font-size:11px}.status-card strong{margin-top:4px;font-size:16px;font-weight:650}.status-card small{margin-top:3px;color:#647488;font-size:10px}.status-card.good .status-icon{color:var(--nvr-green);background:rgba(46,204,138,.09)}.status-card.warn .status-icon{color:var(--nvr-yellow);background:rgba(235,183,64,.09)}.status-card.danger .status-icon{color:var(--nvr-red);background:rgba(240,93,94,.09)}.panel{border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-panel)}.scope-panel{padding:17px;margin-bottom:14px}.panel-title{display:flex;align-items:baseline;gap:10px;margin-bottom:16px}.panel-title strong{font-size:13px}.panel-title span{color:var(--nvr-muted);font-size:11px}.scope-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.scope-item{display:flex;gap:10px;padding:12px;border:1px solid rgba(255,255,255,.055);border-radius:8px;background:rgba(255,255,255,.018)}.scope-dot{flex:0 0 7px;width:7px;height:7px;margin-top:5px;border-radius:50%;background:var(--nvr-blue);box-shadow:0 0 0 3px rgba(76,141,255,.08)}.scope-item strong{font-size:12px}.scope-item p{margin:5px 0 0;color:var(--nvr-muted);font-size:10px;line-height:1.55}.incident-box{margin-top:14px;padding-top:13px;border-top:1px solid var(--nvr-border);font-size:11px}.incident-list{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}.monitor-error{margin-top:12px;padding:9px 11px;border-radius:7px;color:#ffb2b2;background:rgba(240,93,94,.08);font-size:11px}.settings-layout{display:grid;grid-template-columns:minmax(0,.82fr) minmax(0,1.18fr);gap:14px}.settings-layout>.panel{padding:17px}.settings-form :deep(.el-form-item){margin-bottom:17px}.settings-form :deep(.el-form-item__label){color:#98a6b7;font-size:11px}.two-cols{display:grid;grid-template-columns:1fr 1fr;gap:12px}.three-cols{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}.switch-row{display:flex;align-items:center;gap:10px;color:var(--nvr-muted);font-size:11px}.field-hint{display:block;margin-top:6px;color:#657589;font-size:10px}.password-row{display:flex;align-items:center;gap:12px;width:100%;margin-top:8px}
@media(max-width:1100px){.status-grid,.scope-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.settings-layout{grid-template-columns:1fr}}@media(max-width:680px){.alert-page{padding:14px}.status-grid,.scope-grid,.two-cols,.three-cols{grid-template-columns:1fr}.page-actions{justify-content:flex-start}.panel-title{align-items:flex-start;flex-direction:column;gap:4px}}
</style>
