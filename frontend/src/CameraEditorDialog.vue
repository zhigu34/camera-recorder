<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

import CameraDiscoveryDialog from './CameraDiscoveryDialog.vue'
import {
  connectionFingerprint,
  createPayloadFromDraft,
  draftFromCamera,
  emptyCameraDraft,
  passwordRequired,
  probePayloadFromDraft,
  updatePayloadFromDraft,
} from './camera-editor/model'
import type {
  CameraAdapterCapability,
  CameraAdapterId,
  CameraConnectionProbeResult,
  CameraEditorDraft,
  CameraFormFactor,
  TimestampMode,
} from './camera-editor/types'
import type { CameraDiscoverySelection } from './camera-discovery/types'
import type { SharedCamera } from './stores/cameras'

const props = defineProps<{
  modelValue: boolean
  camera: SharedCamera | null
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'saved', cameraId: number): void
}>()

const form = ref<CameraEditorDraft>(emptyCameraDraft())
const adapters = ref<CameraAdapterCapability[]>([])
const adaptersLoading = ref(false)
const saving = ref(false)
const probing = ref(false)
const probeResult = ref<CameraConnectionProbeResult | null>(null)
const probeFingerprint = ref('')
const discoveryVisible = ref(false)

const formFactorOptions: Array<{ value: CameraFormFactor; label: string }> = [
  { value: 'unknown', label: '未指定' },
  { value: 'bullet', label: '枪机' },
  { value: 'dome', label: '半球' },
  { value: 'turret', label: '炮塔 / 海螺' },
  { value: 'ptz', label: '云台 PTZ' },
  { value: 'doorbell', label: '门铃' },
  { value: 'indoor', label: '室内桌面机' },
  { value: 'panoramic', label: '全景 / 鱼眼' },
]

const timestampOptions: Array<{ value: TimestampMode; label: string }> = [
  { value: 'reconstruct', label: '重建时间戳（推荐）' },
  { value: 'native', label: '使用原始时间戳' },
  { value: 'wallclock', label: '使用系统墙钟' },
]

const currentAdapter = computed<CameraAdapterId | null>(() => props.camera?.connection?.adapter || null)
const switchingAdapter = computed(() => Boolean(
  props.camera && currentAdapter.value && currentAdapter.value !== form.value.adapter,
))
const requiresPassword = computed(() => passwordRequired(props.camera, form.value))
const selectedCapability = computed(() => adapters.value.find((item) => item.id === form.value.adapter) || null)
const selectedAdapterUnavailable = computed(() => selectedCapability.value?.available === false)
const canDiscover = computed(() => form.value.adapter === 'manual_rtsp' || form.value.adapter === 'onvif')
const title = computed(() => props.camera ? `编辑摄像头 #${props.camera.id}` : '添加摄像头')

function apiError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    if (detail && typeof detail === 'object') return JSON.stringify(detail)
    return error.message || fallback
  }
  if (error instanceof Error) return error.message
  return fallback
}

function adapterLabel(adapter: CameraAdapterId | null) {
  if (!adapter) return '未配置'
  return adapters.value.find((item) => item.id === adapter)?.label
    || ({ manual_rtsp: 'Manual RTSP', onvif: 'ONVIF', hik_sdk: 'Hikvision SDK' }[adapter])
}

function normalizedHost(value: string) {
  return value.trim().replace(/^\[/, '').replace(/\]$/, '').toLowerCase()
}

function onvifServiceAuthorityMatches(serviceUrl: string, host: string, port: number) {
  try {
    const parsed = new URL(serviceUrl)
    const parsedPort = parsed.port ? Number(parsed.port) : parsed.protocol === 'https:' ? 443 : 80
    return normalizedHost(parsed.hostname) === normalizedHost(host) && parsedPort === port
  } catch {
    return false
  }
}

function openDiscovery() {
  if (!canDiscover.value) return
  discoveryVisible.value = true
}

function applyDiscoverySelection(selection: CameraDiscoverySelection) {
  if (selection.adapter === 'manual_rtsp' && form.value.adapter === 'manual_rtsp') {
    form.value.host = selection.host
    form.value.port = 554
    discoveryVisible.value = false
    return
  }
  if (selection.adapter === 'onvif' && form.value.adapter === 'onvif') {
    form.value.host = selection.host
    form.value.port = selection.port
    form.value.device_service_url = selection.device_service_url
    discoveryVisible.value = false
  }
}

function commonDraft() {
  return {
    name: form.value.name,
    manufacturer: form.value.manufacturer,
    model: form.value.model,
    form_factor: form.value.form_factor,
    enabled: form.value.enabled,
    auto_record: form.value.auto_record,
    timestamp_mode: form.value.timestamp_mode,
    host: form.value.host,
    username: form.value.username,
    password: form.value.password,
  }
}

function changeAdapter(adapter: CameraAdapterId) {
  if (adapter === form.value.adapter) return
  const capability = adapters.value.find((item) => item.id === adapter)
  if (capability && !capability.available) return
  const base = commonDraft()
  if (adapter === 'manual_rtsp') {
    form.value = { ...base, adapter, port: 554, main_path: '/ch1/main', sub_path: '' }
  } else if (adapter === 'onvif') {
    form.value = { ...base, adapter, port: 80, device_service_url: '' }
  } else {
    form.value = {
      ...base,
      adapter,
      sdk_port: 8000,
      channel: 1,
      main_stream_type: 0,
      sub_stream_type: 1,
    }
  }
  discoveryVisible.value = false
  probeResult.value = null
  probeFingerprint.value = ''
}

function reset() {
  form.value = props.camera ? draftFromCamera(props.camera) : emptyCameraDraft()
  probeResult.value = null
  probeFingerprint.value = ''
}

async function loadAdapters() {
  adaptersLoading.value = true
  try {
    const response = await axios.get<CameraAdapterCapability[]>('/api/camera-adapters')
    adapters.value = response.data
  } catch (error) {
    adapters.value = [
      { id: 'manual_rtsp', label: 'Manual RTSP', available: false, unavailable_reason: '能力信息加载失败' },
      { id: 'onvif', label: 'ONVIF', available: false, unavailable_reason: '能力信息加载失败' },
      { id: 'hik_sdk', label: 'Hikvision SDK', available: false, unavailable_reason: '能力信息加载失败' },
    ]
    ElMessage.error(apiError(error, '摄像头适配器能力加载失败'))
  } finally {
    adaptersLoading.value = false
  }
}

function validateConnection(): string | null {
  if (adaptersLoading.value) return '摄像头适配器能力仍在加载'
  if (!selectedCapability.value) return '无法确认所选摄像头适配器能力'
  if (!form.value.host.trim()) return '请填写设备地址'
  if (!form.value.username.trim()) return '请填写用户名'
  if (requiresPassword.value && !form.value.password) return '新增或切换适配器时必须填写密码'
  if (selectedAdapterUnavailable.value && form.value.adapter !== currentAdapter.value) {
    return selectedCapability.value?.unavailable_reason || '所选适配器当前不可用'
  }
  if (form.value.adapter === 'manual_rtsp' && !form.value.main_path.trim()) return '请填写主码流路径'
  return null
}

function validateSave(): string | null {
  if (!form.value.name.trim()) return '请填写摄像头名称'
  return validateConnection()
}

async function probeConnection() {
  const validationError = validateConnection()
  if (validationError) {
    ElMessage.warning(validationError)
    return
  }
  probing.value = true
  try {
    const payload = probePayloadFromDraft(props.camera, form.value)
    const response = await axios.post<CameraConnectionProbeResult>('/api/camera-connections/probe', payload)
    probeResult.value = response.data
    probeFingerprint.value = connectionFingerprint(form.value)

    const device = response.data.device
    const manufacturer = typeof device.manufacturer === 'string' ? device.manufacturer : ''
    const model = typeof device.model === 'string'
      ? device.model
      : typeof device.device_model === 'string' ? device.device_model : ''
    const deviceName = typeof device.device_name === 'string' ? device.device_name : ''
    if (!form.value.manufacturer.trim() && manufacturer) form.value.manufacturer = manufacturer
    if (!form.value.model.trim() && model) form.value.model = model
    if (!form.value.name.trim() && deviceName) form.value.name = deviceName

    ElMessage.success('连接检测成功')
  } catch (error) {
    probeResult.value = null
    probeFingerprint.value = ''
    ElMessage.error(apiError(error, '连接检测失败；仍可保存为未验证连接'))
  } finally {
    probing.value = false
  }
}

async function save() {
  const validationError = validateSave()
  if (validationError) {
    ElMessage.warning(validationError)
    return
  }

  saving.value = true
  try {
    if (props.camera) {
      await axios.put(`/api/cameras/${props.camera.id}`, updatePayloadFromDraft(props.camera, form.value))
      ElMessage.success('摄像头配置已保存')
      emit('saved', props.camera.id)
    } else {
      const response = await axios.post<{ id: number }>('/api/cameras', createPayloadFromDraft(form.value))
      ElMessage.success('摄像头已添加')
      emit('saved', response.data.id)
    }
    emit('update:modelValue', false)
  } catch (error) {
    ElMessage.error(apiError(error, '摄像头保存失败'))
  } finally {
    saving.value = false
  }
}

const probeSummary = computed(() => {
  if (!probeResult.value) return ''
  const media = probeResult.value.media
  const codec = typeof media.video_codec === 'string' ? media.video_codec.toUpperCase() : '视频'
  const width = typeof media.width === 'number' ? media.width : null
  const height = typeof media.height === 'number' ? media.height : null
  return width && height ? `${codec} · ${width}×${height}` : codec
})

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    reset()
    void loadAdapters()
  },
)

watch(
  () => connectionFingerprint(form.value),
  (fingerprint) => {
    if (probeFingerprint.value && probeFingerprint.value !== fingerprint) {
      probeResult.value = null
      probeFingerprint.value = ''
    }
  },
)

watch(
  () => form.value.adapter === 'onvif'
    ? [form.value.host, form.value.port] as const
    : null,
  (authority) => {
    if (!authority || form.value.adapter !== 'onvif' || !form.value.device_service_url) return
    const [host, port] = authority
    if (!onvifServiceAuthorityMatches(form.value.device_service_url, host, port)) {
      form.value.device_service_url = ''
    }
  },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    class="camera-editor-dialog"
    width="min(860px, calc(100vw - 32px))"
    align-center
    destroy-on-close
    :close-on-click-modal="false"
    :title="title"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="camera-editor">
      <section class="camera-editor-section">
        <div class="camera-editor-section-heading">
          <div>
            <span>DEVICE</span>
            <strong>监控点与设备信息</strong>
          </div>
          <small v-if="camera">Camera ID #{{ camera.id }}</small>
        </div>
        <div class="camera-editor-grid camera-editor-grid-identity">
          <el-form-item label="摄像头名称">
            <el-input v-model="form.name" maxlength="128" />
          </el-form-item>
          <el-form-item label="厂商">
            <el-input v-model="form.manufacturer" maxlength="128" placeholder="可选" />
          </el-form-item>
          <el-form-item label="型号">
            <el-input v-model="form.model" maxlength="128" placeholder="可选" />
          </el-form-item>
          <el-form-item label="外形">
            <el-select v-model="form.form_factor">
              <el-option v-for="item in formFactorOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </div>
      </section>

      <section class="camera-editor-section">
        <div class="camera-editor-section-heading">
          <div>
            <span>CONNECTION</span>
            <strong>连接适配器</strong>
          </div>
          <small>检测是可选步骤；未检测或离线设备也可以保存。</small>
        </div>

        <el-form-item label="适配器">
          <el-select
            :model-value="form.adapter"
            :loading="adaptersLoading"
            class="camera-editor-adapter-select"
            @change="changeAdapter"
          >
            <el-option
              v-for="item in adapters"
              :key="item.id"
              :label="item.label"
              :value="item.id"
              :disabled="!item.available && item.id !== form.adapter"
            >
              <div class="camera-editor-adapter-option">
                <span>{{ item.label }}</span>
                <small v-if="!item.available">{{ item.unavailable_reason || '当前不可用' }}</small>
              </div>
            </el-option>
          </el-select>
        </el-form-item>

        <div v-if="selectedCapability && !selectedCapability.available" class="camera-editor-notice warning">
          <strong>{{ selectedCapability.label }} 当前不可用</strong>
          <span>{{ selectedCapability.unavailable_reason || '部署环境未提供该适配器能力。' }}</span>
        </div>

        <div v-if="switchingAdapter" class="camera-editor-notice switch">
          <strong>{{ adapterLabel(currentAdapter) }} → {{ adapterLabel(form.adapter) }}</strong>
          <span>仅替换当前连接；Camera ID #{{ camera?.id }} 与历史录像、事件和健康记录保持不变。</span>
        </div>

        <div class="camera-editor-grid camera-editor-grid-connection">
          <el-form-item label="设备地址">
            <div class="camera-editor-address-row">
              <el-input v-model="form.host" placeholder="192.168.1.120" />
              <el-button
                v-if="form.adapter === 'manual_rtsp' || form.adapter === 'onvif'"
                plain
                :disabled="saving || probing"
                @click="openDiscovery"
              >
                扫描局域网
              </el-button>
            </div>
          </el-form-item>
          <el-form-item label="用户名">
            <el-input v-model="form.username" maxlength="128" autocomplete="username" />
          </el-form-item>
          <el-form-item :label="requiresPassword ? '密码（必填）' : '密码（留空保持原值）'">
            <el-input v-model="form.password" type="password" show-password autocomplete="current-password" />
          </el-form-item>

          <template v-if="form.adapter === 'manual_rtsp'">
            <el-form-item label="RTSP 端口">
              <el-input-number v-model="form.port" :min="1" :max="65535" controls-position="right" />
            </el-form-item>
            <el-form-item label="主码流路径" class="camera-editor-wide">
              <el-input v-model="form.main_path" placeholder="/ch1/main" />
            </el-form-item>
            <el-form-item label="子码流路径" class="camera-editor-wide">
              <el-input v-model="form.sub_path" placeholder="可选，例如 /ch1/sub" />
            </el-form-item>
          </template>

          <template v-else-if="form.adapter === 'onvif'">
            <el-form-item label="ONVIF 端口">
              <el-input-number v-model="form.port" :min="1" :max="65535" controls-position="right" />
            </el-form-item>
          </template>

          <template v-else>
            <el-form-item label="SDK 端口">
              <el-input-number v-model="form.sdk_port" :min="1" :max="65535" controls-position="right" />
            </el-form-item>
            <el-form-item label="通道">
              <el-input-number v-model="form.channel" :min="1" :max="65535" controls-position="right" />
            </el-form-item>
            <el-form-item label="主码流类型">
              <el-input-number v-model="form.main_stream_type" :min="0" :max="255" controls-position="right" />
            </el-form-item>
            <el-form-item label="子码流类型">
              <el-input-number v-model="form.sub_stream_type" :min="0" :max="255" controls-position="right" />
            </el-form-item>
          </template>
        </div>

        <div class="camera-editor-probe-row">
          <el-button
            plain
            :loading="probing"
            :disabled="saving || adaptersLoading || selectedAdapterUnavailable"
            @click="probeConnection"
          >
            检测连接
          </el-button>
          <div v-if="probeResult" class="camera-editor-probe-result">
            <strong>检测成功</strong>
            <span>{{ probeSummary }}</span>
          </div>
          <span v-else class="camera-editor-probe-hint">可跳过检测直接保存，连接状态将显示为未验证。</span>
        </div>
      </section>

      <section class="camera-editor-section">
        <div class="camera-editor-section-heading">
          <div>
            <span>RUNTIME</span>
            <strong>运行与录像策略</strong>
          </div>
        </div>
        <div class="camera-editor-grid camera-editor-grid-policy">
          <el-form-item label="时间戳策略">
            <el-select v-model="form.timestamp_mode">
              <el-option v-for="item in timestampOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="自动录像">
            <el-switch v-model="form.auto_record" />
          </el-form-item>
        </div>
      </section>
    </div>

    <CameraDiscoveryDialog
      v-if="canDiscover"
      v-model="discoveryVisible"
      :adapter="form.adapter === 'onvif' ? 'onvif' : 'manual_rtsp'"
      @selected="applyDiscoverySelection"
    />

    <template #footer>
      <el-button :disabled="saving || probing" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="probing || adaptersLoading" @click="save">
        {{ camera ? '保存修改' : '添加摄像头' }}
      </el-button>
    </template>
  </el-dialog>
</template>
