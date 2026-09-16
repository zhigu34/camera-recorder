<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

interface HikProbeResult {
  ok: boolean
  serial_number?: string | null
  device_type?: number | null
  device_model?: string | null
  device_name?: string | null
  start_channel?: number | null
  analog_channel_count?: number | null
  digital_channel_count?: number | null
  channel: number
}

const emit = defineEmits<{
  (event: 'completed'): void
  (event: 'close'): void
}>()

const form = reactive({
  name: '',
  host: '',
  port: 8000,
  username: 'admin',
  password: '',
  channel: 1,
  auto_record: false,
  timestamp_mode: 'reconstruct' as 'native' | 'reconstruct' | 'wallclock',
})
const detecting = ref(false)
const saving = ref(false)
const detected = ref<HikProbeResult | null>(null)
const detectedFingerprint = ref('')

function apiError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    return error.message || fallback
  }
  return fallback
}

function connectionFingerprint() {
  return [
    form.host.trim(),
    String(form.port),
    form.username.trim(),
    form.password,
    String(form.channel),
  ].join('\n')
}

watch(
  () => [form.host, form.port, form.username, form.password, form.channel],
  () => {
    if (detectedFingerprint.value !== connectionFingerprint()) detected.value = null
  },
)

const canDetect = computed(() => Boolean(
  form.host.trim()
  && form.username.trim()
  && form.password
  && form.port > 0
  && form.port <= 65535
  && form.channel > 0,
))
const canCreate = computed(() => Boolean(
  detected.value && detectedFingerprint.value === connectionFingerprint() && form.name.trim(),
))

async function detect() {
  if (!canDetect.value || detecting.value || saving.value) {
    if (!canDetect.value) ElMessage.warning('请填写 HIK SDK 地址、端口、账号、密码和通道')
    return
  }
  detecting.value = true
  detected.value = null
  try {
    const payload = {
      host: form.host.trim(),
      port: form.port,
      username: form.username.trim(),
      password: form.password,
      channel: form.channel,
    }
    const { data } = await axios.post<HikProbeResult>('/api/cameras/hik/probe', payload)
    detected.value = data
    detectedFingerprint.value = connectionFingerprint()
    if (!form.name.trim()) form.name = data.device_name || data.device_model || form.host.trim()
    ElMessage.success('HCNetSDK 登录成功')
  } catch (error) {
    detectedFingerprint.value = ''
    ElMessage.error(apiError(error, 'HIK SDK 设备检测失败'))
  } finally {
    detecting.value = false
  }
}

async function createCamera() {
  if (!canCreate.value || saving.value || detecting.value) {
    if (!form.name.trim()) ElMessage.warning('请填写摄像头名称')
    else if (!detected.value) ElMessage.warning('请先检测 HIK SDK 设备')
    return
  }
  saving.value = true
  try {
    await axios.post('/api/cameras/hik', {
      name: form.name.trim(),
      host: form.host.trim(),
      port: form.port,
      username: form.username.trim(),
      password: form.password,
      channel: form.channel,
      auto_record: form.auto_record,
      timestamp_mode: form.timestamp_mode,
      enabled: true,
    })
    ElMessage.success('HIK SDK 摄像头已添加')
    emit('completed')
  } catch (error) {
    ElMessage.error(apiError(error, 'HIK SDK 摄像头添加失败'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="hik-add-view">
    <div class="hik-intro">
      <div>
        <span>HIKVISION HCNETSDK</span>
        <strong>通过原生 SDK 独立取流</strong>
      </div>
      <small>录像使用主码流，实时预览与本地事件检测默认使用子码流；不会自动回退到 RTSP 或 ONVIF。</small>
    </div>

    <el-form label-position="top" class="hik-form" @submit.prevent>
      <div class="form-grid identity-grid">
        <el-form-item label="摄像头名称">
          <el-input v-model="form.name" maxlength="128" placeholder="例如：仓库海康" />
        </el-form-item>
        <el-form-item label="设备地址">
          <el-input v-model="form.host" placeholder="192.168.1.120" />
        </el-form-item>
        <el-form-item label="SDK 端口">
          <el-input-number v-model="form.port" :min="1" :max="65535" controls-position="right" />
        </el-form-item>
      </div>

      <div class="form-grid auth-grid">
        <el-form-item label="用户名">
          <el-input v-model="form.username" maxlength="128" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="通道">
          <el-input-number v-model="form.channel" :min="1" :max="65535" controls-position="right" />
        </el-form-item>
        <div class="detect-cell">
          <el-button type="primary" plain :loading="detecting" :disabled="!canDetect || saving" @click="detect">
            检测 HIK SDK
          </el-button>
        </div>
      </div>

      <div v-if="detected" class="discovery-card">
        <div class="discovery-heading">
          <div>
            <span>设备已识别</span>
            <strong>{{ detected.device_name || detected.device_model || 'Hikvision 摄像头' }}</strong>
          </div>
          <small>{{ detected.serial_number || '序列号未返回' }}</small>
        </div>
        <div class="profile-grid">
          <div><span>SDK 设备类型</span><strong>{{ detected.device_type ?? '未知' }}</strong></div>
          <div><span>当前通道</span><strong>{{ detected.channel }}</strong></div>
          <div><span>模拟通道</span><strong>{{ detected.analog_channel_count ?? 0 }}</strong></div>
          <div><span>数字通道</span><strong>{{ detected.digital_channel_count ?? 0 }}</strong></div>
        </div>
      </div>

      <div class="policy-row">
        <el-form-item label="时间戳策略">
          <el-select v-model="form.timestamp_mode">
            <el-option label="重建时间戳（推荐）" value="reconstruct" />
            <el-option label="使用原始时间戳" value="native" />
            <el-option label="使用系统墙钟" value="wallclock" />
          </el-select>
        </el-form-item>
        <el-form-item label="自动录像">
          <el-switch v-model="form.auto_record" />
        </el-form-item>
      </div>
    </el-form>

    <footer class="hik-actions">
      <el-button :disabled="saving || detecting" @click="emit('close')">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="!canCreate || detecting" @click="createCamera">
        添加 HIK SDK 摄像头
      </el-button>
    </footer>
  </section>
</template>

<style scoped>
.hik-add-view{display:flex;flex-direction:column;min-height:0;color:var(--nvr-text)}
.hik-intro{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:18px 20px;border-bottom:1px solid var(--nvr-border);background:var(--nvr-surface-2)}
.hik-intro div{display:flex;flex-direction:column;gap:4px}.hik-intro span{color:var(--nvr-blue);font-size:9px;font-weight:700;letter-spacing:.1em}.hik-intro strong{font-size:14px;font-weight:650}.hik-intro small{max-width:420px;color:var(--nvr-muted);font-size:10px;line-height:1.5;text-align:right}
.hik-form{padding:18px 20px 6px}.form-grid{display:grid;gap:12px}.identity-grid{grid-template-columns:minmax(0,1.4fr) minmax(0,1fr) 150px}.auth-grid{grid-template-columns:minmax(0,1fr) minmax(0,1fr) 120px 150px}.detect-cell{display:flex;align-items:flex-end;padding-bottom:18px}.detect-cell .el-button{width:100%}.hik-form :deep(.el-form-item__label){color:var(--nvr-muted);font-size:10px}.hik-form :deep(.el-input-number),.hik-form :deep(.el-select){width:100%}
.discovery-card{margin:4px 0 18px;border:1px solid var(--nvr-border);border-radius:9px;background:var(--nvr-surface-2);overflow:hidden}.discovery-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 14px;border-bottom:1px solid var(--nvr-border)}.discovery-heading div{display:flex;flex-direction:column;gap:3px}.discovery-heading span,.profile-grid span{color:var(--nvr-muted);font-size:9px}.discovery-heading strong{font-size:12px}.discovery-heading small{color:var(--nvr-muted);font-size:9px}.profile-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.profile-grid>div{display:flex;flex-direction:column;gap:4px;padding:11px 14px;border-right:1px solid var(--nvr-border);border-bottom:1px solid var(--nvr-border)}.profile-grid>div:nth-child(2n){border-right:0}.profile-grid>div:nth-last-child(-n+2){border-bottom:0}.profile-grid strong{font-size:10px;font-weight:600;overflow-wrap:anywhere}
.policy-row{display:grid;grid-template-columns:minmax(0,1fr) 150px;gap:12px;align-items:start}.hik-actions{display:flex;justify-content:flex-end;gap:8px;padding:14px 20px;border-top:1px solid var(--nvr-border);background:var(--nvr-surface-2)}
@media(max-width:760px){.hik-intro{flex-direction:column}.hik-intro small{text-align:left}.identity-grid,.auth-grid,.policy-row{grid-template-columns:1fr}.detect-cell{padding-bottom:18px}.profile-grid{grid-template-columns:1fr}.profile-grid>div{border-right:0}.profile-grid>div:nth-last-child(-n+2){border-bottom:1px solid var(--nvr-border)}.profile-grid>div:last-child{border-bottom:0}}
</style>
