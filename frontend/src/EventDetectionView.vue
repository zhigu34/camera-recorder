<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Refresh, VideoPause, VideoPlay } from '@element-plus/icons-vue'

import MotionZoneEditor from './MotionZoneEditor.vue'
import {
  cameraIdFromDetectionQuery,
  countMotionDraftChanges,
  motionDraftFromSource,
  serializeMotionSourcePayload,
} from './event-detection/state'
import type {
  CameraSummary,
  DetectionCapabilitySlot,
  DetectionEventType,
  EventDetectionOverview,
  EventSourceRead,
  MotionSourceDraft,
  MotionZoneRead,
} from './event-detection/types'
import { eventDetectionRoute } from './navigation'
import type { NormalizedPoint } from './utils/motionZones'

const route = useRoute()
const router = useRouter()

const cameras = ref<CameraSummary[]>([])
const overview = ref<EventDetectionOverview | null>(null)
const motionSource = ref<EventSourceRead | null>(null)
const onvifSource = ref<EventSourceRead | null>(null)
const savedDraft = ref<MotionSourceDraft | null>(null)
const draft = ref<MotionSourceDraft | null>(null)
const loading = ref(false)
const cameraListLoading = ref(false)
const saving = ref(false)
const onvifToggling = ref(false)
const previewActive = ref(false)
const previewNonce = ref(Date.now())
const previewFailed = ref(false)
const editorVisible = ref(false)
const editingZoneId = ref<number | null>(null)
const zoneSaving = ref(false)
const zoneDraft = reactive<{ name: string; polygon: NormalizedPoint[] }>({ name: '', polygon: [] })
let requestToken = 0

const selectedCameraId = computed(() => cameraIdFromDetectionQuery(route.query.camera_id))
const selectedCamera = computed(() => cameras.value.find((camera) => camera.id === selectedCameraId.value) || null)
const dirtyCount = computed(() => countMotionDraftChanges(savedDraft.value, draft.value))
const zones = computed(() => motionSource.value?.zones || [])
const enabledZoneCount = computed(() => zones.value.filter((zone) => zone.enabled).length)
const capabilitySlots = computed(() => overview.value?.capability_slots || [])
const sourceDescriptors = computed(() => overview.value?.sources || [])
const previewSrc = computed(() => selectedCameraId.value
  ? `/api/cameras/${selectedCameraId.value}/preview.mjpeg?stream=auto&t=${previewNonce.value}`
  : '')
const zoneOverlays = computed(() => zones.value.map((zone) => ({
  id: zone.id,
  name: zone.name,
  enabled: zone.enabled,
  polygon: zone.polygon as NormalizedPoint[],
})))
const editorTitle = computed(() => editingZoneId.value ? '重新绘制检测区域' : '添加检测区域')
const motionRuntimeState = computed(() => motionSource.value?.descriptor.runtime_state || 'disabled')
const onvifRuntimeState = computed(() => onvifSource.value?.descriptor.runtime_state || 'disabled')
const onvifEnabled = computed(() => onvifSource.value?.config.enabled === true)

function errorText(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    return error.message || fallback
  }
  return fallback
}

function runtimeLabel(state: string | null | undefined) {
  if (state === 'warming_up') return '背景学习中'
  if (state === 'stabilizing') return '画面稳定中'
  if (state === 'running') return '检测中'
  if (state === 'starting') return '启动中'
  if (state === 'reconnecting') return '正在重连'
  if (state === 'error') return '检测异常'
  if (state === 'stopped') return '等待启动'
  return '未启用'
}

function sourceStatusLabel(status: string) {
  if (status === 'available') return '可用'
  if (status === 'unsupported') return '不支持'
  if (status === 'error') return '异常'
  return '不可用'
}

function capabilityLabel(type: DetectionEventType) {
  const labels: Record<DetectionEventType, string> = {
    motion: '移动',
    person: '人员',
    vehicle: '车辆',
    intrusion: '入侵',
    tamper: '遮挡 / 防拆',
    digital_input: '数字输入',
    unknown: '其他事件',
  }
  return labels[type]
}

function capabilityReason(slot: DetectionCapabilitySlot) {
  if (slot.reason) return slot.reason
  if (slot.event_type === 'person' || slot.event_type === 'vehicle') return '未安装 AI Provider'
  if (slot.status !== 'available') return '尚无可用 Provider'
  return '当前来源可用'
}

function cameraStatus(camera: CameraSummary) {
  const state = String(camera.connectivity_status || camera.status || 'unknown')
  if (!camera.enabled) return '已停用'
  if (state === 'online') return '在线'
  if (state === 'offline') return '离线'
  return '未知'
}

function cloneDraft(value: MotionSourceDraft): MotionSourceDraft {
  return { ...value }
}

function resetDraft() {
  if (savedDraft.value) draft.value = cloneDraft(savedDraft.value)
}

function confirmDiscard() {
  return dirtyCount.value === 0 || window.confirm('事件检测设置还有未保存的修改，确定放弃吗？')
}

function beforeUnload(event: BeforeUnloadEvent) {
  if (!dirtyCount.value) return
  event.preventDefault()
  event.returnValue = ''
}

async function loadCameras() {
  cameraListLoading.value = true
  try {
    cameras.value = (await axios.get<CameraSummary[]>('/api/cameras')).data
    if (!cameras.value.length) {
      overview.value = null
      motionSource.value = null
      onvifSource.value = null
      savedDraft.value = null
      draft.value = null
      return
    }

    const requested = selectedCameraId.value
    const requestedExists = requested != null && cameras.value.some((camera) => camera.id === requested)
    if (requestedExists && requested != null) {
      await loadSelectedCamera(requested)
      return
    }

    const fallback = cameras.value.find((camera) => camera.enabled) || cameras.value[0]
    if (route.query.camera_id != null) ElMessage.warning('指定的摄像头不存在，已切换到可用摄像头')
    await router.replace(eventDetectionRoute(fallback.id))
  } catch (error) {
    ElMessage.error(errorText(error, '摄像头列表加载失败'))
  } finally {
    cameraListLoading.value = false
  }
}

async function loadSelectedCamera(cameraId: number) {
  const token = ++requestToken
  loading.value = true
  previewActive.value = false
  previewFailed.value = false
  closeZoneEditor()
  try {
    const overviewResponse = await axios.get<EventDetectionOverview>(`/api/cameras/${cameraId}/event-detection`)
    if (token !== requestToken) return
    overview.value = overviewResponse.data

    const [sourceResponse, onvifResponse] = await Promise.all([
      axios.get<EventSourceRead>(
        `/api/cameras/${cameraId}/event-detection/sources/local.motion`,
      ),
      axios.get<EventSourceRead>(
        `/api/cameras/${cameraId}/event-detection/sources/camera.onvif`,
      ),
    ])
    if (token !== requestToken) return
    motionSource.value = sourceResponse.data
    onvifSource.value = onvifResponse.data
    const value = motionDraftFromSource(sourceResponse.data)
    savedDraft.value = value
    draft.value = cloneDraft(value)
  } catch (error) {
    if (token === requestToken) ElMessage.error(errorText(error, '事件检测配置加载失败'))
  } finally {
    if (token === requestToken) loading.value = false
  }
}

async function reloadMotionSource() {
  const cameraId = selectedCameraId.value
  if (!cameraId) return
  try {
    motionSource.value = (await axios.get<EventSourceRead>(
      `/api/cameras/${cameraId}/event-detection/sources/local.motion`,
    )).data
  } catch (error) {
    ElMessage.error(errorText(error, '检测区域刷新失败'))
  }
}

async function selectCamera(cameraId: number) {
  if (cameraId === selectedCameraId.value) return
  await router.push(eventDetectionRoute(cameraId))
}

function togglePreview() {
  previewActive.value = !previewActive.value
  previewFailed.value = false
  if (previewActive.value) previewNonce.value = Date.now()
}

function refreshPreview() {
  previewFailed.value = false
  previewActive.value = true
  previewNonce.value = Date.now()
}

async function saveSettings() {
  const cameraId = selectedCameraId.value
  if (!cameraId || !draft.value || saving.value) return
  saving.value = true
  try {
    const response = await axios.put<EventSourceRead>(
      `/api/cameras/${cameraId}/event-detection/sources/local.motion`,
      serializeMotionSourcePayload(draft.value),
    )
    motionSource.value = response.data
    const value = motionDraftFromSource(response.data)
    savedDraft.value = value
    draft.value = cloneDraft(value)
    if (overview.value) {
      const enabled = new Set(overview.value.enabled_source_ids)
      if (value.enabled) enabled.add('local.motion')
      else enabled.delete('local.motion')
      overview.value = { ...overview.value, enabled_source_ids: [...enabled] }
    }
    ElMessage.success(value.enabled ? '移动检测设置已保存' : '移动检测已关闭')
  } catch (error) {
    ElMessage.error(errorText(error, '事件检测设置保存失败'))
  } finally {
    saving.value = false
  }
}

async function toggleOnvifSource(value: string | number | boolean) {
  const cameraId = selectedCameraId.value
  if (!cameraId || !onvifSource.value || onvifToggling.value) return
  const enabled = Boolean(value)
  onvifToggling.value = true
  try {
    onvifSource.value = (await axios.put<EventSourceRead>(
      `/api/cameras/${cameraId}/event-detection/sources/camera.onvif`,
      { enabled },
    )).data
    overview.value = (await axios.get<EventDetectionOverview>(
      `/api/cameras/${cameraId}/event-detection`,
    )).data
    ElMessage.success(enabled ? 'ONVIF 原生事件已启用' : 'ONVIF 原生事件已关闭')
  } catch (error) {
    ElMessage.error(errorText(error, enabled
      ? 'ONVIF 原生事件启用失败'
      : 'ONVIF 原生事件关闭失败'))
  } finally {
    onvifToggling.value = false
  }
}

function openCreateZone() {
  editingZoneId.value = null
  zoneDraft.name = `检测区域 ${zones.value.length + 1}`
  zoneDraft.polygon = []
  editorVisible.value = true
}

function openEditZone(zone: MotionZoneRead) {
  editingZoneId.value = zone.id
  zoneDraft.name = zone.name
  zoneDraft.polygon = zone.polygon.map(([x, y]) => [x, y])
  editorVisible.value = true
}

function closeZoneEditor() {
  editorVisible.value = false
  editingZoneId.value = null
  zoneDraft.name = ''
  zoneDraft.polygon = []
}

async function saveZone() {
  const cameraId = selectedCameraId.value
  if (!cameraId) return
  if (!zoneDraft.name.trim()) return ElMessage.warning('请填写区域名称')
  if (zoneDraft.polygon.length < 3) return ElMessage.warning('检测区域至少需要 3 个顶点')
  zoneSaving.value = true
  try {
    const payload = { name: zoneDraft.name.trim(), enabled: true, polygon: zoneDraft.polygon }
    if (editingZoneId.value) {
      const current = zones.value.find((zone) => zone.id === editingZoneId.value)
      await axios.put(`/api/cameras/${cameraId}/motion-zones/${editingZoneId.value}`, {
        ...payload,
        enabled: current?.enabled ?? true,
      })
    } else {
      await axios.post(`/api/cameras/${cameraId}/motion-zones`, payload)
    }
    ElMessage.success(editingZoneId.value ? '检测区域已更新' : '检测区域已添加')
    closeZoneEditor()
    await reloadMotionSource()
  } catch (error) {
    ElMessage.error(errorText(error, '检测区域保存失败'))
  } finally {
    zoneSaving.value = false
  }
}

async function toggleZone(zone: MotionZoneRead, value: string | number | boolean) {
  const cameraId = selectedCameraId.value
  if (!cameraId) return
  try {
    await axios.put(`/api/cameras/${cameraId}/motion-zones/${zone.id}`, { enabled: Boolean(value) })
    await reloadMotionSource()
  } catch (error) {
    ElMessage.error(errorText(error, '区域状态更新失败'))
  }
}

async function removeZone(zone: MotionZoneRead) {
  const cameraId = selectedCameraId.value
  if (!cameraId) return
  try {
    await ElMessageBox.confirm(`确认删除检测区域“${zone.name}”？`, '删除检测区域', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
    await axios.delete(`/api/cameras/${cameraId}/motion-zones/${zone.id}`)
    ElMessage.success('检测区域已删除')
    await reloadMotionSource()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorText(error, '检测区域删除失败'))
  }
}

onBeforeRouteUpdate((to, from) => {
  const nextId = cameraIdFromDetectionQuery(to.query.camera_id)
  const currentId = cameraIdFromDetectionQuery(from.query.camera_id)
  if (nextId !== currentId && !confirmDiscard()) return false
  return true
})
onBeforeRouteLeave(() => confirmDiscard())

watch(selectedCameraId, (cameraId, previous) => {
  if (cameraId && cameraId !== previous) void loadSelectedCamera(cameraId)
})

onMounted(() => {
  window.addEventListener('beforeunload', beforeUnload)
  void loadCameras()
})
onBeforeUnmount(() => {
  requestToken += 1
  window.removeEventListener('beforeunload', beforeUnload)
})
</script>

<template>
  <section class="event-detection-page" v-loading="loading || cameraListLoading">
    <aside class="detection-camera-rail">
      <div class="detection-rail-head">
        <span>检测摄像头</span>
        <b>{{ cameras.length }}</b>
      </div>
      <div v-if="cameras.length" class="detection-camera-list">
        <button
          v-for="camera in cameras"
          :key="camera.id"
          class="detection-camera-row"
          :class="{ active: selectedCameraId === camera.id }"
          @click="selectCamera(camera.id)"
        >
          <span class="camera-state-dot" :class="String(camera.connectivity_status || camera.status || 'unknown')"></span>
          <span class="camera-row-copy"><strong>{{ camera.name }}</strong><small>{{ cameraStatus(camera) }}</small></span>
          <span v-if="selectedCameraId === camera.id && draft?.enabled" class="camera-motion-mark">检测中</span>
        </button>
      </div>
      <div v-else class="detection-empty">尚未添加摄像头</div>
    </aside>

    <main class="detection-main">
      <header class="detection-page-head">
        <div>
          <span class="detection-eyebrow">事件检测</span>
          <h1>{{ selectedCamera?.name || '事件检测' }}</h1>
          <p>统一管理移动检测、检测区域与未来智能事件来源。</p>
        </div>
        <el-button :icon="Refresh" :disabled="!selectedCameraId" @click="selectedCameraId && loadSelectedCamera(selectedCameraId)">刷新</el-button>
      </header>

      <section v-if="selectedCameraId" class="detection-preview-card">
        <div class="preview-stage">
          <img v-if="previewActive && !previewFailed" :src="previewSrc" :alt="`${selectedCamera?.name || '摄像头'} 实时预览`" @error="previewFailed = true" />
          <div v-else class="preview-placeholder">
            <VideoPlay />
            <strong>{{ previewFailed ? '预览连接失败' : '实时预览默认关闭' }}</strong>
            <span>需要确认区域或画面时再打开，不会为列表中的摄像头批量拉流。</span>
          </div>
        </div>
        <div class="preview-toolbar">
          <div><strong>实时画面</strong><span>自动优先低码率流，失败时由后端策略回退。</span></div>
          <div>
            <el-button v-if="previewActive" :icon="Refresh" @click="refreshPreview">重连</el-button>
            <el-button :icon="previewActive ? VideoPause : VideoPlay" @click="togglePreview">{{ previewActive ? '停止预览' : '打开预览' }}</el-button>
          </div>
        </div>
      </section>

      <section
        v-if="onvifSource && onvifSource.descriptor.status !== 'unsupported'"
        class="detection-settings-card onvif-source-settings"
      >
        <div class="settings-card-head">
          <div>
            <span>摄像头原生 Provider</span>
            <strong>ONVIF PullPoint Events</strong>
            <small>订阅摄像头原生事件；连接状态与事件订阅状态彼此独立。</small>
          </div>
          <div class="motion-master">
            <span class="runtime-pill" :class="onvifRuntimeState">
              <i></i>{{ runtimeLabel(onvifRuntimeState) }}
            </span>
            <el-switch
              :model-value="onvifEnabled"
              :loading="onvifToggling"
              :disabled="!['available', 'error'].includes(onvifSource.descriptor.status)"
              @change="toggleOnvifSource"
            />
          </div>
        </div>
        <div class="onvif-source-copy">
          <strong>{{ sourceStatusLabel(onvifSource.descriptor.status) }}</strong>
          <span v-if="onvifSource.descriptor.capabilities.length">
            已识别：{{ onvifSource.descriptor.capabilities.map(capabilityLabel).join('、') }}
          </span>
          <span v-else>{{ onvifSource.descriptor.reason || '设备已公布 Events 服务，尚未识别具体 Topic。' }}</span>
          <small>为避免重复移动事件，camera.onvif 与 local.motion 不能同时启用。</small>
        </div>
      </section>

      <section v-if="draft && motionSource" class="detection-settings-card">
        <div class="settings-card-head">
          <div>
            <span>本地 Provider</span>
            <strong>移动检测</strong>
            <small>使用低码率画面分析运动，不影响主码流连续录像。</small>
          </div>
          <div class="motion-master">
            <span class="runtime-pill" :class="motionRuntimeState"><i></i>{{ runtimeLabel(motionRuntimeState) }}</span>
            <el-switch v-model="draft.enabled" />
          </div>
        </div>

        <div class="detection-setting-grid">
          <label>
            <span>灵敏度</span>
            <small>越高越容易发现细小移动，也更容易受到光影变化影响。</small>
            <el-select v-model="draft.sensitivity"><el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /></el-select>
          </label>
          <label>
            <span>分析帧率</span>
            <small>提高帧率可捕捉更快移动，但会增加 CPU 使用。</small>
            <el-select v-model="draft.analysis_fps"><el-option label="3 FPS" :value="3" /><el-option label="5 FPS" :value="5" /><el-option label="8 FPS" :value="8" /></el-select>
          </label>
          <label>
            <span>分析宽度</span>
            <small>检测分辨率越高，对小物体变化更敏感。</small>
            <el-select v-model="draft.analysis_width"><el-option label="480 px" :value="480" /><el-option label="640 px" :value="640" /><el-option label="960 px" :value="960" /></el-select>
          </label>
          <label>
            <span>最短移动时间</span>
            <small>过滤短暂抖动或瞬时画面变化。</small>
            <el-select v-model="draft.min_duration_ms"><el-option label="0.3 秒" :value="300" /><el-option label="0.5 秒" :value="500" /><el-option label="0.8 秒" :value="800" /><el-option label="1.5 秒" :value="1500" /><el-option label="3 秒" :value="3000" /></el-select>
          </label>
          <label>
            <span>连续活动合并</span>
            <small>短暂停止后在此时间内再次移动，继续作为同一事件。</small>
            <el-select v-model="draft.merge_gap_ms"><el-option label="3 秒" :value="3000" /><el-option label="5 秒" :value="5000" /><el-option label="10 秒" :value="10000" /><el-option label="15 秒" :value="15000" /><el-option label="30 秒" :value="30000" /></el-select>
          </label>
          <label>
            <span>事件最小间隔</span>
            <small>降低回放事件锚点密度；0 秒表示关闭归并。</small>
            <el-select v-model="draft.event_min_interval_ms"><el-option label="关闭" :value="0" /><el-option label="15 秒" :value="15000" /><el-option label="30 秒" :value="30000" /><el-option label="60 秒" :value="60000" /><el-option label="120 秒" :value="120000" /><el-option label="300 秒" :value="300000" /></el-select>
          </label>
        </div>

        <div class="detection-zone-section">
          <div class="zone-section-head">
            <div><strong>检测区域</strong><span>{{ enabledZoneCount ? `已启用 ${enabledZoneCount} 个区域` : '未启用区域时检测整个画面' }}</span></div>
            <el-button size="small" :icon="Plus" @click="openCreateZone">添加区域</el-button>
          </div>
          <div v-if="zones.length" class="detection-zone-list">
            <div v-for="zone in zones" :key="zone.id" class="detection-zone-row">
              <div><strong>{{ zone.name }}</strong><span>{{ zone.polygon.length }} 个顶点</span></div>
              <div>
                <el-switch :model-value="zone.enabled" size="small" @change="toggleZone(zone, $event)" />
                <el-button text :icon="Edit" @click="openEditZone(zone)">重绘</el-button>
                <el-button text type="danger" :icon="Delete" @click="removeZone(zone)">删除</el-button>
              </div>
            </div>
          </div>
          <div v-else class="zone-empty-state"><strong>当前检测整个画面</strong><span>添加区域后可只关注入口、通道或装卸区。</span></div>
        </div>

        <div v-if="editorVisible" class="zone-editor-shell">
          <div class="zone-editor-head"><strong>{{ editorTitle }}</strong><el-input v-model="zoneDraft.name" maxlength="128" placeholder="区域名称" /></div>
          <MotionZoneEditor v-model="zoneDraft.polygon" :camera-id="selectedCameraId" :zones="zoneOverlays" />
          <div class="zone-editor-actions"><el-button @click="closeZoneEditor">取消</el-button><el-button type="primary" :loading="zoneSaving" @click="saveZone">保存区域</el-button></div>
        </div>

        <div class="detection-savebar" :class="{ dirty: dirtyCount > 0 }">
          <span>{{ dirtyCount ? `已修改 ${dirtyCount} 项（尚未保存）` : '移动检测设置已同步' }}</span>
          <div><el-button :disabled="!dirtyCount || saving" @click="resetDraft">重置</el-button><el-button type="primary" :loading="saving" :disabled="!dirtyCount" @click="saveSettings">保存设置</el-button></div>
        </div>
      </section>

      <div v-else-if="cameras.length && !loading" class="detection-empty main-empty">请选择摄像头查看事件检测配置</div>
    </main>

    <aside class="detection-capability-rail">
      <section class="capability-card">
        <div class="capability-head"><span>来源</span><strong>事件 Provider</strong></div>
        <div v-if="sourceDescriptors.length" class="source-list">
          <div v-for="source in sourceDescriptors" :key="source.id" class="source-row">
            <div><strong>{{ source.display_name }}</strong><span>{{ source.id }}</span></div>
            <b :class="source.status">{{ sourceStatusLabel(source.status) }}</b>
          </div>
        </div>
        <div v-else class="capability-empty">选择摄像头后显示来源状态</div>
      </section>

      <section class="capability-card">
        <div class="capability-head"><span>能力</span><strong>检测能力</strong></div>
        <div v-if="capabilitySlots.length" class="capability-list">
          <div v-for="slot in capabilitySlots" :key="slot.event_type" class="capability-row" :class="slot.status">
            <div><strong>{{ capabilityLabel(slot.event_type) }}</strong><span>{{ capabilityReason(slot) }}</span></div>
            <b>{{ sourceStatusLabel(slot.status) }}</b>
          </div>
        </div>
        <div v-else class="capability-empty">人员 / 车辆能力需要安装 AI Provider；未安装 AI Provider 时不会显示可用开关。</div>
      </section>
    </aside>
  </section>
</template>
