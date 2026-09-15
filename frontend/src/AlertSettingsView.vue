<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Bell, CircleCheckFilled, Message, Monitor, Plus, Delete, WarningFilled } from '@element-plus/icons-vue'
import { formatDateTime } from './utils/dateTime'

interface EmailRecipient { name: string; address: string }
interface EmailSettings {
  email_enabled: boolean
  offline_alert_seconds: number
  recovery_stable_seconds: number
  notify_recovery: boolean
  smtp_sender_name: string
  smtp_host: string
  smtp_port: number
  smtp_auth_enabled: boolean
  smtp_username: string
  smtp_password_set: boolean
  smtp_from: string
  smtp_to: string
  recipients: EmailRecipient[]
  smtp_use_ssl: boolean
  smtp_starttls: boolean
  smtp_timeout_seconds: number
  email_attach_images: boolean
  email_capture_interval_seconds: number
  configured: boolean
}
interface SystemStatus {
  upload?: { enabled: boolean; configured: boolean; active: boolean }
  storage?: { used_percent: number; state: 'healthy' | 'warning' | 'critical'; warning_percent: number; critical_percent: number }
  alerts?: {
    monitor?: { running: boolean; last_check_at?: string | null; last_error?: string | null; last_event_id?: number }
    dispatcher?: { active_incidents?: string[]; active_count?: number }
  }
}

const emit = defineEmits<{ (event: 'open-events'): void }>()
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const testingRecipient = ref('')
const status = ref<SystemStatus | null>(null)
const passwordConfirm = ref('')
const recipients = ref<EmailRecipient[]>([])
let statusTimer: number | null = null

const form = reactive({
  email_enabled: false,
  offline_alert_seconds: 60,
  recovery_stable_seconds: 10,
  notify_recovery: true,
  smtp_sender_name: 'Camera Recorder',
  smtp_host: '',
  smtp_port: 587,
  smtp_auth_enabled: true,
  smtp_username: '',
  smtp_password: '',
  smtp_password_set: false,
  clear_smtp_password: false,
  smtp_from: '',
  smtp_use_ssl: false,
  smtp_starttls: true,
  smtp_timeout_seconds: 15,
  email_attach_images: false,
  email_capture_interval_seconds: 2,
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
const validRecipients = computed(() => recipients.value.filter((item) => item.address.trim()))
const scopeItems = computed(() => [
  { title: '摄像头离线', detail: `持续离线 ${form.offline_alert_seconds} 秒后发送告警` },
  { title: 'FFmpeg 连续失败', detail: '录像进程连续失败时发送一次告警，恢复后自动清除事故状态' },
  { title: '磁盘空间', detail: `warning ${status.value?.storage?.warning_percent ?? '-'}% · critical ${status.value?.storage?.critical_percent ?? '-'}%` },
  { title: '上传失败', detail: status.value?.upload?.enabled ? 'OpenList/WebDAV 上传耗尽重试后发送告警' : '上传功能关闭时不检查上传失败' },
])

function applySettings(data: EmailSettings) {
  Object.assign(form, data, { smtp_password: '', clear_smtp_password: false })
  passwordConfirm.value = ''
  recipients.value = data.recipients?.length
    ? data.recipients.map((item) => ({ name: item.name || '', address: item.address || '' }))
    : (data.smtp_to || '').split(',').map((address) => ({ name: '', address: address.trim() })).filter((item) => item.address)
  if (!recipients.value.length) recipients.value = [{ name: '', address: '' }]
}
function errorText(error: unknown, fallback: string) {
  return axios.isAxiosError(error) ? error.response?.data?.detail || error.message : fallback
}
async function loadStatus() {
  try { status.value = (await axios.get<SystemStatus>('/api/system/status')).data } catch { /* keep last good state */ }
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
  } catch (error) { ElMessage.error(errorText(error, '加载告警配置失败')) }
  finally { loading.value = false }
}
function enableSsl(value: boolean | string | number) { if (Boolean(value)) form.smtp_starttls = false }
function enableStarttls(value: boolean | string | number) { if (Boolean(value)) form.smtp_use_ssl = false }
function passwordChanged() { if (form.smtp_password) form.clear_smtp_password = false }
function addRecipient() { recipients.value.push({ name: '', address: '' }) }
function removeRecipient(index: number) {
  recipients.value.splice(index, 1)
  if (!recipients.value.length) addRecipient()
}

async function save() {
  if (form.smtp_password && form.smtp_password !== passwordConfirm.value) {
    ElMessage.warning('两次输入的 SMTP 密码不一致')
    return
  }
  saving.value = true
  try {
    const recipientPayload = validRecipients.value.map((item) => ({ name: item.name.trim(), address: item.address.trim() }))
    const payload = {
      email_enabled: form.email_enabled,
      offline_alert_seconds: form.offline_alert_seconds,
      recovery_stable_seconds: form.recovery_stable_seconds,
      notify_recovery: form.notify_recovery,
      smtp_sender_name: form.smtp_sender_name,
      smtp_host: form.smtp_host,
      smtp_port: form.smtp_port,
      smtp_auth_enabled: form.smtp_auth_enabled,
      smtp_username: form.smtp_username,
      smtp_password: form.smtp_password || null,
      clear_smtp_password: form.clear_smtp_password,
      smtp_from: form.smtp_from,
      smtp_to: recipientPayload.map((item) => item.address).join(','),
      recipients: recipientPayload,
      smtp_use_ssl: form.smtp_use_ssl,
      smtp_starttls: form.smtp_starttls,
      smtp_timeout_seconds: form.smtp_timeout_seconds,
      email_attach_images: form.email_attach_images,
      email_capture_interval_seconds: form.email_capture_interval_seconds,
    }
    const { data } = await axios.put<EmailSettings>('/api/notifications/email', payload)
    applySettings(data)
    await loadStatus()
    ElMessage.success('告警配置已保存并立即生效')
  } catch (error) { ElMessage.error(errorText(error, '保存告警配置失败')) }
  finally { saving.value = false }
}
async function testEmail(address?: string) {
  const target = (address || '').trim()
  if (address && !target) return ElMessage.warning('请先填写收件人地址并保存')
  testing.value = !address
  testingRecipient.value = target
  try {
    await axios.post('/api/notifications/email/test', null, { params: target ? { recipient: target } : undefined })
    ElMessage.success(target ? `测试邮件已发送至 ${target}` : '测试邮件已发送，请检查收件箱')
    await loadStatus()
  } catch (error) { ElMessage.error(errorText(error, '测试邮件发送失败')) }
  finally { testing.value = false; testingRecipient.value = '' }
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
  return formatDateTime(status.value?.alerts?.monitor?.last_check_at)
}

onMounted(() => { void load(); statusTimer = window.setInterval(loadStatus, 15000) })
onBeforeUnmount(() => { if (statusTimer !== null) window.clearInterval(statusTimer) })
</script>

<template>
  <section class="alert-page" v-loading="loading">
    <div class="page-actions">
      <el-button @click="load">刷新</el-button>
      <el-button plain @click="emit('open-events')">查看事件中心</el-button>
      <el-button :loading="testing" @click="testEmail()">测试全部收件人</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
    </div>

    <div class="status-grid">
      <article class="status-card" :class="{ good: alertReady, warn: !alertReady }"><div class="status-icon"><Message /></div><div><span>邮件告警</span><strong>{{ emailStateText }}</strong></div></article>
      <article class="status-card" :class="{ good: monitorRunning, warn: !monitorRunning }"><div class="status-icon"><Monitor /></div><div><span>告警监控器</span><strong>{{ monitorRunning ? '运行中' : '未运行' }}</strong><small>最近检查 {{ lastCheckText() }}</small></div></article>
      <article class="status-card" :class="{ danger: activeIncidents.length > 0, good: activeIncidents.length === 0 }"><div class="status-icon"><WarningFilled v-if="activeIncidents.length" /><CircleCheckFilled v-else /></div><div><span>当前事故</span><strong>{{ activeIncidents.length }}</strong><small>{{ activeIncidents.length ? '存在尚未恢复的告警' : '没有活动事故' }}</small></div></article>
      <article class="status-card"><div class="status-icon"><Bell /></div><div><span>恢复通知</span><strong>{{ form.notify_recovery ? '已开启' : '已关闭' }}</strong><small>事故恢复后{{ form.notify_recovery ? '发送' : '不发送' }}邮件</small></div></article>
    </div>

    <div class="scope-panel panel">
      <div class="panel-title"><strong>告警范围</strong><span>后台统一去重，同一事故不会连续轰炸邮箱。</span></div>
      <div class="scope-grid"><div v-for="item in scopeItems" :key="item.title" class="scope-item"><div class="scope-dot"></div><div><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></div></div></div>
      <div v-if="activeIncidents.length" class="incident-box"><strong>活动事故</strong><div class="incident-list"><el-tag v-for="incident in activeIncidents" :key="incident" type="danger" effect="dark">{{ incidentLabel(incident) }}</el-tag></div></div>
      <div v-if="status?.alerts?.monitor?.last_error" class="monitor-error">监控器错误：{{ status.alerts.monitor.last_error }}</div>
    </div>

    <div class="settings-layout">
      <div class="panel policy-panel">
        <div class="panel-title"><strong>告警策略</strong><span>事件判定和恢复行为。</span></div>
        <el-form label-position="top" class="settings-form">
          <el-form-item label="邮件告警"><div class="switch-row"><el-switch v-model="form.email_enabled" /><span>关闭后仍记录事件，但不会发送邮件。</span></div></el-form-item>
          <div class="two-cols">
            <el-form-item label="摄像头持续离线"><el-input-number v-model="form.offline_alert_seconds" :min="0" :max="86400" :step="10" /><span class="field-hint">秒后触发告警</span></el-form-item>
            <el-form-item label="恢复稳定时间"><el-input-number v-model="form.recovery_stable_seconds" :min="0" :max="3600" :step="5" /><span class="field-hint">连续稳定后才判定恢复</span></el-form-item>
          </div>
          <el-form-item label="恢复邮件"><div class="switch-row"><el-switch v-model="form.notify_recovery" /><span>故障恢复后发送恢复通知。</span></div></el-form-item>
          <div class="media-options">
            <div><strong>图片附件</strong><span>仅在事件本身提供抓图时附加图片；离线、磁盘等无图事件不会强制抓图。</span></div><el-switch v-model="form.email_attach_images" />
          </div>
          <el-form-item v-if="form.email_attach_images" label="抓图时间间隔">
            <el-select v-model="form.email_capture_interval_seconds" style="width:150px"><el-option v-for="seconds in [2,3,4,5,10]" :key="seconds" :label="`${seconds} 秒`" :value="seconds" /></el-select>
            <span class="field-hint">供后续支持连续事件抓图时使用。</span>
          </el-form-item>
        </el-form>
      </div>

      <div class="panel smtp-panel">
        <div class="panel-title"><strong>邮件服务器</strong><span>参数按常见 NVR 邮件能力整理，视觉仍使用本系统组件。</span></div>
        <el-form label-position="top" class="settings-form smtp-form">
          <div class="two-cols">
            <el-form-item label="发件人名称"><el-input v-model="form.smtp_sender_name" placeholder="Camera Recorder" /></el-form-item>
            <el-form-item label="发件人地址"><el-input v-model="form.smtp_from" placeholder="nvr@example.com" /></el-form-item>
            <el-form-item label="SMTP 服务器"><el-input v-model="form.smtp_host" placeholder="smtp.example.com" /></el-form-item>
            <el-form-item label="SMTP 端口"><el-input-number v-model="form.smtp_port" :min="1" :max="65535" /></el-form-item>
          </div>

          <div class="smtp-switches">
            <div class="switch-row"><el-switch v-model="form.smtp_use_ssl" @change="enableSsl" /><span>SSL（常见 465）</span></div>
            <div class="switch-row"><el-switch v-model="form.smtp_starttls" @change="enableStarttls" /><span>STARTTLS（常见 587）</span></div>
            <div class="switch-row"><el-switch v-model="form.smtp_auth_enabled" /><span>服务器认证</span></div>
          </div>

          <div v-if="form.smtp_auth_enabled" class="auth-grid">
            <el-form-item label="用户名"><el-input v-model="form.smtp_username" autocomplete="username" /></el-form-item>
            <el-form-item label="密码 / 授权码"><el-input v-model="form.smtp_password" type="password" show-password autocomplete="new-password" :placeholder="form.smtp_password_set ? '已加密保存；留空保持不变' : '请输入密码或授权码'" @input="passwordChanged" /></el-form-item>
            <el-form-item label="密码确认"><el-input v-model="passwordConfirm" type="password" show-password autocomplete="new-password" :placeholder="form.smtp_password ? '再次输入新密码' : '未修改密码无需填写'" /></el-form-item>
            <el-form-item label="连接超时"><div class="inline-number"><el-input-number v-model="form.smtp_timeout_seconds" :min="1" :max="120" /><span>秒</span></div></el-form-item>
          </div>
          <div v-if="form.smtp_password_set && form.smtp_auth_enabled" class="password-row"><el-tag size="small" type="success">凭据已加密保存</el-tag><el-checkbox v-model="form.clear_smtp_password">清除已保存密码</el-checkbox></div>
        </el-form>

        <div class="recipient-head"><div><strong>收件人</strong><span>支持名称 + 邮箱地址，多收件人会同时收到通知。</span></div><el-button size="small" :icon="Plus" @click="addRecipient">添加收件人</el-button></div>
        <div class="recipient-table">
          <div class="recipient-row recipient-labels"><span>名称</span><span>邮箱地址</span><span>测试</span><span></span></div>
          <div v-for="(recipient, index) in recipients" :key="index" class="recipient-row">
            <el-input v-model="recipient.name" placeholder="运维人员" />
            <el-input v-model="recipient.address" placeholder="ops@example.com" />
            <el-button size="small" :loading="testingRecipient === recipient.address.trim()" :disabled="!recipient.address.trim()" @click="testEmail(recipient.address)">发送测试</el-button>
            <el-button size="small" text type="danger" :icon="Delete" title="删除" @click="removeRecipient(index)" />
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.alert-page{padding:18px 20px 28px;color:var(--nvr-text)}.page-actions{display:flex;justify-content:flex-end;gap:8px;margin-bottom:12px;flex-wrap:wrap}.status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin-bottom:10px}.status-card{min-height:76px;display:flex;align-items:center;gap:10px;padding:11px 12px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-panel)}.status-icon{flex:0 0 32px;width:32px;height:32px;display:grid;place-items:center;border-radius:8px;color:var(--nvr-muted);background:var(--nvr-surface-2)}.status-icon :deep(svg){width:16px}.status-card>div:last-child{min-width:0;display:flex;flex-direction:column}.status-card span{color:var(--nvr-muted);font-size:10px}.status-card strong{margin-top:3px;font-size:13px;font-weight:650}.status-card small{margin-top:2px;color:var(--nvr-subtle);font-size:9px}.status-card.good .status-icon{color:var(--nvr-green);background:rgba(46,204,138,.09)}.status-card.warn .status-icon{color:var(--nvr-yellow);background:rgba(235,183,64,.09)}.status-card.danger .status-icon{color:var(--nvr-red);background:rgba(240,93,94,.09)}.panel{border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-panel)}.scope-panel{padding:13px;margin-bottom:10px}.panel-title{display:flex;align-items:baseline;gap:9px;margin-bottom:12px}.panel-title strong{font-size:12px}.panel-title span{color:var(--nvr-muted);font-size:10px}.scope-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.scope-item{display:flex;gap:9px;padding:10px;border:1px solid var(--nvr-border);border-radius:8px;background:var(--nvr-surface-2)}.scope-dot{flex:0 0 6px;width:6px;height:6px;margin-top:5px;border-radius:50%;background:var(--nvr-blue)}.scope-item strong{font-size:11px}.scope-item p{margin:4px 0 0;color:var(--nvr-muted);font-size:9px;line-height:1.5}.incident-box{margin-top:12px;padding-top:11px;border-top:1px solid var(--nvr-border);font-size:10px}.incident-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}.monitor-error{margin-top:10px;padding:8px 10px;border-radius:7px;color:#ffb2b2;background:rgba(240,93,94,.08);font-size:10px}.settings-layout{display:grid;grid-template-columns:minmax(320px,.72fr) minmax(560px,1.28fr);gap:10px;align-items:start}.settings-layout>.panel{padding:14px}.settings-form :deep(.el-form-item){margin-bottom:12px}.settings-form :deep(.el-form-item__label){height:auto;padding-bottom:5px;color:var(--nvr-muted);font-size:10px;line-height:1.3}.two-cols,.auth-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 12px}.switch-row{display:flex;align-items:center;gap:8px;color:var(--nvr-muted);font-size:10px}.field-hint{display:block;width:100%;margin-top:5px;color:var(--nvr-subtle);font-size:9px}.media-options{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:2px 0 12px;padding:10px;border:1px solid var(--nvr-border);border-radius:8px;background:var(--nvr-surface-2)}.media-options>div{display:flex;flex-direction:column;gap:3px}.media-options strong{font-size:10px}.media-options span{color:var(--nvr-muted);font-size:9px;line-height:1.45}.smtp-switches{display:flex;flex-wrap:wrap;gap:14px;margin:0 0 12px;padding:9px 10px;border:1px solid var(--nvr-border);border-radius:8px;background:var(--nvr-surface-2)}.inline-number{display:flex;align-items:center;gap:8px;width:100%}.inline-number .el-input-number{flex:1}.inline-number span{color:var(--nvr-muted);font-size:10px}.password-row{display:flex;align-items:center;gap:12px;margin:-3px 0 12px}.recipient-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:2px;padding-top:12px;border-top:1px solid var(--nvr-border)}.recipient-head>div{display:flex;flex-direction:column;gap:3px}.recipient-head strong{font-size:11px}.recipient-head span{color:var(--nvr-muted);font-size:9px}.recipient-table{margin-top:9px;border:1px solid var(--nvr-border);border-radius:8px;overflow:hidden}.recipient-row{display:grid;grid-template-columns:minmax(120px,.7fr) minmax(220px,1.4fr) 90px 34px;gap:8px;align-items:center;padding:8px 9px;border-top:1px solid var(--nvr-border)}.recipient-row:first-child{border-top:0}.recipient-labels{padding-top:7px;padding-bottom:7px;color:var(--nvr-muted);background:var(--nvr-surface-2);font-size:9px}.recipient-row :deep(.el-input__wrapper){min-height:30px}
@media(max-width:1100px){.status-grid,.scope-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.settings-layout{grid-template-columns:1fr}.smtp-panel{order:2}}@media(max-width:680px){.alert-page{padding:14px}.status-grid,.scope-grid,.two-cols,.auth-grid{grid-template-columns:1fr}.page-actions{justify-content:flex-start}.panel-title{align-items:flex-start;flex-direction:column;gap:4px}.recipient-row{grid-template-columns:1fr}.recipient-labels{display:none}.recipient-row .el-button{justify-self:start}}
</style>
