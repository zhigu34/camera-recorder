<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter, type RouteLocationRaw } from 'vue-router'

import type { CameraDeletionImpact } from './camera-management/types'
import type { SharedCamera } from './stores/cameras'
import {
  cameraActivityRoute,
  cameraHealthRoute,
  cameraRecordingsRoute,
  cameraSystemEventsRoute,
  cameraUploadsRoute,
} from './navigation'

const props = defineProps<{
  modelValue: boolean
  camera: SharedCamera | null
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'deleted', cameraId: number): void
  (event: 'disabled', cameraId: number): void
}>()

const router = useRouter()
const loading = ref(false)
const deleting = ref(false)
const disabling = ref(false)
const impact = ref<CameraDeletionImpact | null>(null)
const confirmName = ref('')
const error = ref('')
let requestId = 0

const blockers = computed(() => impact.value ? [
  { key: 'recordings', label: '录像', count: impact.value.recordings, route: cameraRecordingsRoute(impact.value.camera_id) },
  { key: 'motion', label: '移动活动', count: impact.value.motion_events, route: cameraActivityRoute(impact.value.camera_id) },
  { key: 'events', label: '阻塞事件', count: impact.value.blocking_events, route: cameraSystemEventsRoute(impact.value.camera_id) },
  { key: 'health', label: '健康样本', count: impact.value.health_samples, route: cameraHealthRoute(impact.value.camera_id) },
  { key: 'uploads', label: '待处理上传', count: impact.value.pending_uploads, route: cameraUploadsRoute(impact.value.camera_id) },
].filter((item) => item.count > 0) : [])

const canConfirmDelete = computed(() =>
  Boolean(props.camera && impact.value?.can_delete && confirmName.value === props.camera.name),
)

function isDeletionImpact(value: unknown): value is CameraDeletionImpact {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<CameraDeletionImpact>
  return Number.isInteger(candidate.camera_id)
    && typeof candidate.recordings === 'number'
    && typeof candidate.motion_events === 'number'
    && typeof candidate.health_samples === 'number'
    && typeof candidate.blocking_events === 'number'
    && typeof candidate.pending_uploads === 'number'
    && typeof candidate.can_delete === 'boolean'
}

function apiError(errorValue: unknown, fallback: string) {
  if (axios.isAxiosError(errorValue)) {
    const detail = errorValue.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    return errorValue.message || fallback
  }
  return fallback
}

function resetState() {
  requestId += 1
  impact.value = null
  error.value = ''
  confirmName.value = ''
}

async function loadImpact() {
  if (!props.camera) return
  const id = props.camera.id
  const current = ++requestId
  loading.value = true
  error.value = ''
  confirmName.value = ''
  try {
    const response = await axios.get<CameraDeletionImpact>(`/api/cameras/${id}/deletion-impact`)
    if (current === requestId) impact.value = response.data
  } catch (errorValue) {
    if (current === requestId) {
      impact.value = null
      error.value = apiError(errorValue, '删除影响读取失败')
    }
  } finally {
    if (current === requestId) loading.value = false
  }
}

async function disableCamera() {
  if (!props.camera || disabling.value) return
  try {
    await ElMessageBox.confirm(
      '禁用后将停止录像、连接探测与重连、移动检测和事件预录；历史录像、事件、健康数据与配置仍会保留。',
      `禁用“${props.camera.name}”`,
      { type: 'warning', confirmButtonText: '确认禁用', cancelButtonText: '取消' },
    )
  } catch (errorValue) {
    if (errorValue === 'cancel' || errorValue === 'close') return
    ElMessage.error('禁用确认失败')
    return
  }

  disabling.value = true
  try {
    await axios.put(`/api/cameras/${props.camera.id}`, { enabled: false })
    ElMessage.success('摄像头已禁用，历史数据保持不变')
    emit('disabled', props.camera.id)
  } catch (errorValue) {
    ElMessage.error(apiError(errorValue, '禁用摄像头失败'))
  } finally {
    disabling.value = false
  }
}

async function deleteCamera() {
  if (!props.camera || deleting.value || !canConfirmDelete.value) return
  deleting.value = true
  try {
    const latest = await axios.get<CameraDeletionImpact>(`/api/cameras/${props.camera.id}/deletion-impact`)
    impact.value = latest.data
    if (!latest.data.can_delete) {
      confirmName.value = ''
      ElMessage.warning('删除前检测到新的关联历史，已阻止永久删除')
      return
    }
    await axios.delete(`/api/cameras/${props.camera.id}`)
    ElMessage.success('摄像头配置已永久删除')
    emit('deleted', props.camera.id)
    emit('update:modelValue', false)
  } catch (errorValue) {
    if (axios.isAxiosError(errorValue) && errorValue.response?.status === 409) {
      const detail = errorValue.response.data?.detail
      if (isDeletionImpact(detail)) {
        impact.value = detail
        confirmName.value = ''
        ElMessage.warning('删除前关联历史发生变化，已阻止永久删除')
        return
      }
    }
    ElMessage.error(apiError(errorValue, '删除摄像头失败'))
  } finally {
    deleting.value = false
  }
}

function openBlocker(route: RouteLocationRaw) {
  emit('update:modelValue', false)
  void router.push(route)
}

watch(
  () => [props.modelValue, props.camera?.id] as const,
  ([open]) => {
    if (open && props.camera) void loadImpact()
    else resetState()
  },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    class="camera-deletion-impact-dialog"
    width="min(620px, calc(100vw - 28px))"
    align-center
    destroy-on-close
    :close-on-click-modal="false"
    title="删除摄像头"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="camera" class="camera-delete-impact" v-loading="loading">
      <div class="camera-delete-target">
        <span>DANGER ZONE</span>
        <strong>{{ camera.name }} · Camera ID #{{ camera.id }}</strong>
        <small>永久删除只删除没有历史依赖的空设备配置，不会级联清理录像、事件、健康样本或上传任务。</small>
      </div>

      <div v-if="error" class="camera-delete-error">{{ error }}</div>

      <template v-else-if="impact">
        <section v-if="!impact.can_delete" class="camera-delete-blocked">
          <strong>当前不能删除：存在关联历史</strong>
          <span>先处理或保留下列数据。这里不会提供级联删除。</span>
          <div class="camera-delete-blocker-list">
            <button v-for="item in blockers" :key="item.key" type="button" @click="openBlocker(item.route)">
              <span>{{ item.label }}</span>
              <strong>{{ item.count }}</strong>
              <small>查看 ›</small>
            </button>
          </div>
          <div class="camera-delete-blocked-actions">
            <el-button
              v-if="camera.enabled"
              :loading="disabling"
              :disabled="deleting"
              @click="disableCamera"
            >
              禁用摄像头
            </el-button>
            <span>禁用会停止运行任务，但不会删除这些历史数据。</span>
          </div>
        </section>

        <section v-else class="camera-delete-confirm">
          <strong>没有检测到阻塞历史，可以永久删除配置。</strong>
          <span>请输入完整摄像头名称 <b>{{ camera.name }}</b> 以确认。</span>
          <el-input v-model="confirmName" :placeholder="camera.name" autocomplete="off" />
        </section>
      </template>
    </div>

    <template #footer>
      <el-button :disabled="deleting || disabling" @click="emit('update:modelValue', false)">取消</el-button>
      <el-button
        v-if="impact?.can_delete"
        type="danger"
        :loading="deleting"
        :disabled="!canConfirmDelete || loading || disabling"
        @click="deleteCamera"
      >
        永久删除
      </el-button>
    </template>
  </el-dialog>
</template>
