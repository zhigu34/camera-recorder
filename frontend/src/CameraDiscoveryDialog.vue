<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import axios from 'axios'

import { scopeLabel } from './camera-discovery/presentation'
import type {
  CameraDiscoveryAdapter,
  CameraDiscoverySelection,
  OnvifDiscoveryCandidate,
  OnvifDiscoveryResponse,
  RtspDiscoveryCandidate,
  RtspDiscoveryResponse,
} from './camera-discovery/types'

const props = defineProps<{
  modelValue: boolean
  adapter: CameraDiscoveryAdapter
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'selected', value: CameraDiscoverySelection): void
}>()

const loading = ref(false)
const error = ref('')
const warnings = ref<string[]>([])
const network = ref('')
const onvifDevices = ref<OnvifDiscoveryCandidate[]>([])
const rtspDevices = ref<RtspDiscoveryCandidate[]>([])
let requestId = 0

const title = computed(() => props.adapter === 'onvif' ? '扫描局域网 ONVIF 设备' : '扫描局域网 RTSP 设备')
const count = computed(() => props.adapter === 'onvif' ? onvifDevices.value.length : rtspDevices.value.length)

function apiError(errorValue: unknown) {
  if (axios.isAxiosError(errorValue)) {
    const detail = errorValue.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    return errorValue.message || '局域网扫描失败'
  }
  return errorValue instanceof Error ? errorValue.message : '局域网扫描失败'
}

async function scan() {
  const currentRequest = ++requestId
  loading.value = true
  error.value = ''
  warnings.value = []
  network.value = ''
  onvifDevices.value = []
  rtspDevices.value = []
  try {
    if (props.adapter === 'onvif') {
      const response = await axios.post<OnvifDiscoveryResponse>('/api/camera-discovery/onvif')
      if (currentRequest !== requestId) return
      onvifDevices.value = response.data.devices
      warnings.value = response.data.warnings
    } else {
      const response = await axios.post<RtspDiscoveryResponse>('/api/camera-discovery/rtsp')
      if (currentRequest !== requestId) return
      rtspDevices.value = response.data.devices
      network.value = response.data.network
      warnings.value = response.data.warnings
    }
  } catch (scanError) {
    if (currentRequest !== requestId) return
    error.value = apiError(scanError)
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

function selectRtsp(device: RtspDiscoveryCandidate) {
  emit('selected', {
    adapter: 'manual_rtsp',
    host: device.host,
    port: 554,
  })
  emit('update:modelValue', false)
}

function selectOnvif(device: OnvifDiscoveryCandidate) {
  if (!device.selectable || !device.host || !device.port || !device.device_service_url) return
  emit('selected', {
    adapter: 'onvif',
    host: device.host,
    port: device.port,
    device_service_url: device.device_service_url,
  })
  emit('update:modelValue', false)
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) void scan()
    else requestId += 1
  },
)

watch(
  () => props.adapter,
  () => {
    if (props.modelValue) void scan()
  },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    append-to-body
    destroy-on-close
    class="camera-discovery-dialog"
    width="min(760px, calc(100vw - 32px))"
    :title="title"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="camera-discovery-toolbar">
      <div>
        <strong>{{ loading ? '正在扫描…' : `发现 ${count} 台候选设备` }}</strong>
        <span v-if="adapter === 'manual_rtsp' && network">扫描范围 {{ network }} · TCP 554</span>
        <span v-else-if="adapter === 'onvif'">WS-Discovery · 不使用摄像头账号密码</span>
      </div>
      <el-button plain :loading="loading" @click="scan">重新扫描</el-button>
    </div>

    <el-alert
      v-if="error"
      type="warning"
      :closable="false"
      show-icon
      :title="error"
      description="仍可关闭扫描窗口并手工填写设备地址。"
    />

    <div v-if="warnings.length" class="camera-discovery-warnings">
      <span v-for="warning in warnings" :key="warning">{{ warning }}</span>
    </div>

    <div v-if="!loading && !error && count === 0" class="camera-discovery-empty">
      当前网段没有发现候选设备。你仍然可以返回后手工填写地址。
    </div>

    <div v-if="adapter === 'manual_rtsp'" class="camera-discovery-list">
      <article v-for="device in rtspDevices" :key="`${device.host}:${device.port}`" class="camera-discovery-item">
        <div>
          <strong>{{ device.host }}:{{ device.port }}</strong>
          <span>TCP 554 可连接；未探测 RTSP 路径和认证。</span>
        </div>
        <el-button type="primary" plain @click="selectRtsp(device)">选择</el-button>
      </article>
    </div>

    <div v-else class="camera-discovery-list">
      <article
        v-for="device in onvifDevices"
        :key="device.endpoint_reference || device.device_service_url || device.host || JSON.stringify(device.scopes)"
        class="camera-discovery-item"
        :class="{ unavailable: !device.selectable }"
      >
        <div>
          <strong>{{ device.host || device.endpoint_reference || 'ONVIF 候选设备' }}</strong>
          <span v-if="device.device_service_url">{{ device.device_service_url }}</span>
          <span v-else>{{ device.unavailable_reason || '没有可用 Device Service 地址' }}</span>
          <small v-if="device.scopes.length">{{ device.scopes.slice(0, 3).map(scopeLabel).join(' · ') }}</small>
        </div>
        <el-button
          type="primary"
          plain
          :disabled="!device.selectable"
          @click="selectOnvif(device)"
        >
          选择
        </el-button>
      </article>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>
