<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue'
import MotionZoneEditor from './MotionZoneEditor.vue'
import type { NormalizedPoint } from './utils/motionZones'

interface MotionRuntime {
  state: 'disabled' | 'starting' | 'running' | 'reconnecting' | 'error' | 'stopped'
  stream?: 'main' | 'sub' | null
  last_frame_at?: string | null
  last_error?: string | null
}
interface MotionZone {
  id: number
  camera_id: number
  name: string
  enabled: boolean
  polygon: NormalizedPoint[]
}
interface MotionConfig {
  enabled: boolean
  sensitivity: 'low' | 'medium' | 'high'
  analysis_fps: number
  analysis_width: number
  min_duration_ms: number
  merge_gap_ms: number
  event_min_interval_ms: number
  runtime: MotionRuntime
  zones: MotionZone[]
}

const props = defineProps<{
  cameraId: number
  cameraName?: string
}>()

const loading = ref(false)
const saving = ref(false)
const zoneSaving = ref(false)
const config = ref<MotionConfig | null>(null)
const editorVisible = ref(false)
const editingZoneId = ref<number | null>(null)
const zoneDraft = reactive<{ name: string; polygon: NormalizedPoint[] }>({ name: '', polygon: [] })

const runtimeLabel = computed(() => {
  const state = config.value?.runtime.state
  if (state === 'running') return '检测中'
  if (state === 'starting') return '启动中'
  if (state === 'reconnecting') return '正在重连'
  if (state === 'error') return '检测异常'
  if (state === 'stopped') return '等待启动'
  return '未启用'
})
const runtimeClass = computed(() => config.value?.runtime.state || 'disabled')
const streamLabel = computed(() => config.value?.runtime.stream === 'sub' ? '子码流' : config.value?.runtime.stream === 'main' ? '主码流' : '-')
const editorTitle = computed(() => editingZoneId.value ? '重新绘制检测区域' : '添加检测区域')
const enabledZoneCount = computed(() => config.value?.zones.filter((zone) => zone.enabled).length || 0)

function errorText(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    return error.message || fallback
  }
  return fallback
}

async function load() {
  loading.value = true
  try {
    config.value = (await axios.get<MotionConfig>(`/api/cameras/${props.cameraId}/motion-detection`)).data
  } catch (error) {
    ElMessage.error(errorText(error, '移动检测配置加载失败'))
  } finally { loading.value = false }
}

async function saveSettings() {
  const value = config.value
  if (!value || saving.value) return
  saving.value = true
  try {
    config.value = (await axios.put<MotionConfig>(`/api/cameras/${props.cameraId}/motion-detection`, {
      enabled: value.enabled,
      sensitivity: value.sensitivity,
      analysis_fps: value.analysis_fps,
      analysis_width: value.analysis_width,
      min_duration_ms: value.min_duration_ms,
      merge_gap_ms: value.merge_gap_ms,
      event_min_interval_ms: value.event_min_interval_ms,
    })).data
    ElMessage.success(value.enabled ? '移动检测配置已保存' : '移动检测已关闭')
  } catch (error) {
    ElMessage.error(errorText(error, '移动检测配置保存失败'))
    await load()
  } finally { saving.value = false }
}

function openCreateZone() {
  editingZoneId.value = null
  zoneDraft.name = `检测区域 ${(config.value?.zones.length || 0) + 1}`
  zoneDraft.polygon = []
  editorVisible.value = true
}

function openEditZone(zone: MotionZone) {
  editingZoneId.value = zone.id
  zoneDraft.name = zone.name
  zoneDraft.polygon = zone.polygon.map(([x, y]) => [x, y])
  editorVisible.value = true
}

function closeEditor() {
  editorVisible.value = false
  editingZoneId.value = null
  zoneDraft.name = ''
  zoneDraft.polygon = []
}

async function saveZone() {
  if (!zoneDraft.name.trim()) return ElMessage.warning('请填写区域名称')
  if (zoneDraft.polygon.length < 3) return ElMessage.warning('检测区域至少需要 3 个顶点')
  zoneSaving.value = true
  try {
    const payload = { name: zoneDraft.name.trim(), enabled: true, polygon: zoneDraft.polygon }
    if (editingZoneId.value) {
      const existing = config.value?.zones.find((zone) => zone.id === editingZoneId.value)
      await axios.put(`/api/cameras/${props.cameraId}/motion-zones/${editingZoneId.value}`, {
        ...payload,
        enabled: existing?.enabled ?? true,
      })
    } else {
      await axios.post(`/api/cameras/${props.cameraId}/motion-zones`, payload)
    }
    ElMessage.success(editingZoneId.value ? '检测区域已更新' : '检测区域已添加')
    closeEditor()
    await load()
  } catch (error) {
    ElMessage.error(errorText(error, '检测区域保存失败'))
  } finally { zoneSaving.value = false }
}

async function toggleZone(zone: MotionZone) {
  try {
    await axios.put(`/api/cameras/${props.cameraId}/motion-zones/${zone.id}`, { enabled: zone.enabled })
    await load()
  } catch (error) {
    ElMessage.error(errorText(error, '区域状态更新失败'))
    zone.enabled = !zone.enabled
  }
}

async function removeZone(zone: MotionZone) {
  try {
    await ElMessageBox.confirm(`确认删除检测区域“${zone.name}”？`, '删除检测区域', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
    await axios.delete(`/api/cameras/${props.cameraId}/motion-zones/${zone.id}`)
    ElMessage.success('检测区域已删除')
    await load()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorText(error, '检测区域删除失败'))
  }
}

function formatFrameTime(value?: string | null) {
  if (!value) return '尚未收到画面'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : `最近帧 ${date.toLocaleTimeString('zh-CN', { hour12: false })}`
}

watch(() => props.cameraId, () => { closeEditor(); void load() })
onMounted(() => void load())
</script>

<template>
  <section class="motion-panel" v-loading="loading">
    <div class="motion-hero">
      <div>
        <span>移动检测</span>
        <strong>{{ cameraName || `摄像头 #${ cameraId }` }}</strong>
        <small>使用低码率画面检测运动，不影响主码流录像。</small>
      </div>
      <div class="motion-master">
        <span class="runtime-pill" :class="runtimeClass"><i></i>{{ runtimeLabel }}</span>
        <el-switch v-if="config" v-model="config.enabled" :loading="saving" @change="saveSettings" />
      </div>
    </div>

    <template v-if="config">
      <div class="runtime-strip">
        <span>分析流 <b>{{ streamLabel }}</b></span>
        <span>{{ config.analysis_width }}px · {{ config.analysis_fps }} FPS</span>
        <span>{{ formatFrameTime(config.runtime.last_frame_at) }}</span>
        <el-button text size="small" :icon="Refresh" @click="load">刷新</el-button>
      </div>
      <div v-if="config.runtime.last_error" class="runtime-error">{{ config.runtime.last_error }}</div>

      <div class="setting-section">
        <div class="setting-section-head"><strong>检测分析</strong><span>控制系统如何读取画面变化。</span></div>
        <div class="setting-grid">
          <label>
            <span>灵敏度</span>
            <small>越高越容易检测到较小移动，也更容易受到光线变化、树影等影响。</small>
            <el-select v-model="config.sensitivity" @change="saveSettings"><el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /></el-select>
          </label>
          <label>
            <span>分析帧率</span>
            <small>每秒用于检测的画面数量。帧率越高，对快速移动更敏感，但会增加 CPU 使用。</small>
            <el-select v-model="config.analysis_fps" @change="saveSettings"><el-option label="3 FPS" :value="3" /><el-option label="5 FPS" :value="5" /><el-option label="8 FPS" :value="8" /></el-select>
          </label>
        </div>
      </div>

      <div class="setting-section">
        <div class="setting-section-head"><strong>事件策略</strong><span>移动事件主要作为回放锚点，以下参数用于过滤噪声并减少过密事件。</span></div>
        <div class="setting-grid event-strategy-grid">
          <label>
            <span>最短移动时间</span>
            <small>移动持续达到此时间后才记录为有效活动，可过滤短暂抖动和瞬时画面变化。</small>
            <el-select v-model="config.min_duration_ms" @change="saveSettings"><el-option label="0.3 秒" :value="300" /><el-option label="0.5 秒" :value="500" /><el-option label="0.8 秒" :value="800" /><el-option label="1.5 秒" :value="1500" /><el-option label="3 秒" :value="3000" /></el-select>
          </label>
          <label>
            <span>连续活动合并</span>
            <small>移动短暂停止后，在此时间内再次出现，会继续算作同一次活动。</small>
            <el-select v-model="config.merge_gap_ms" @change="saveSettings"><el-option label="3 秒" :value="3000" /><el-option label="5 秒" :value="5000" /><el-option label="10 秒" :value="10000" /><el-option label="15 秒" :value="15000" /><el-option label="30 秒" :value="30000" /></el-select>
          </label>
          <label>
            <span>事件最小间隔</span>
            <small>控制回放锚点密度。此时间内再次检测到移动时归并到最近活动；0 秒表示关闭。</small>
            <el-select v-model="config.event_min_interval_ms" @change="saveSettings"><el-option label="关闭" :value="0" /><el-option label="15 秒" :value="15000" /><el-option label="30 秒" :value="30000" /><el-option label="60 秒" :value="60000" /><el-option label="120 秒" :value="120000" /><el-option label="300 秒" :value="300000" /></el-select>
          </label>
        </div>
      </div>

      <div class="zone-section">
        <div class="zone-head"><div><strong>检测区域</strong><span>{{ enabledZoneCount ? '仅启用区域内的运动会生成事件' : '没有启用检测区域时，默认检测整个画面' }}</span></div><el-button size="small" :icon="Plus" @click="openCreateZone">添加区域</el-button></div>
        <div v-if="config.zones.length" class="zone-list">
          <div v-for="zone in config.zones" :key="zone.id" class="zone-row">
            <div><strong>{{ zone.name }}</strong><span>{{ zone.polygon.length }} 个顶点</span></div>
            <div class="zone-actions"><el-switch v-model="zone.enabled" size="small" @change="toggleZone(zone)" /><el-button text :icon="Edit" @click="openEditZone(zone)">重绘</el-button><el-button text type="danger" :icon="Delete" @click="removeZone(zone)">删除</el-button></div>
          </div>
        </div>
        <div v-else class="zone-empty"><strong>当前检测整个画面</strong><span>添加区域后，可以只关注入口、通道或装卸区等位置。</span></div>
      </div>

      <div v-if="editorVisible" class="zone-editor-card">
        <div class="zone-editor-head"><strong>{{ editorTitle }}</strong><el-input v-model="zoneDraft.name" maxlength="128" placeholder="区域名称" /></div>
        <MotionZoneEditor v-model="zoneDraft.polygon" :camera-id="cameraId" :zones="config.zones" />
        <div class="zone-editor-actions"><el-button @click="closeEditor">取消</el-button><el-button type="primary" :loading="zoneSaving" @click="saveZone">保存区域</el-button></div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.motion-panel{display:flex;flex-direction:column;gap:12px;color:var(--nvr-text)}.motion-hero{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:15px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.motion-hero>div:first-child{display:flex;flex-direction:column;gap:4px}.motion-hero span,.zone-head span,.zone-row span,.zone-empty span{color:var(--nvr-muted);font-size:10px}.motion-hero strong{font-size:14px}.motion-hero small{color:var(--nvr-subtle);font-size:10px}.motion-master{display:flex;align-items:center;gap:10px}.runtime-pill{display:flex;align-items:center;gap:6px;padding:4px 7px;border-radius:6px;background:var(--nvr-surface-2);font-size:10px!important}.runtime-pill i{width:6px;height:6px;border-radius:50%;background:var(--nvr-subtle)}.runtime-pill.running i{background:var(--nvr-green)}.runtime-pill.starting i,.runtime-pill.reconnecting i{background:var(--nvr-yellow)}.runtime-pill.error i{background:var(--nvr-red)}.runtime-strip{display:flex;align-items:center;gap:12px;padding:0 3px;color:var(--nvr-muted);font-size:10px}.runtime-strip b{color:var(--nvr-text-soft);font-weight:600}.runtime-strip .el-button{margin-left:auto}.runtime-error{padding:9px 10px;border:1px solid color-mix(in srgb,var(--nvr-red) 25%,var(--nvr-border));border-radius:7px;color:var(--nvr-red);background:color-mix(in srgb,var(--nvr-red) 6%,transparent);font-size:10px;word-break:break-all}.setting-section{display:flex;flex-direction:column;gap:8px}.setting-section-head{display:flex;align-items:baseline;gap:8px;padding:0 2px}.setting-section-head strong{font-size:11px}.setting-section-head span{color:var(--nvr-subtle);font-size:9px}.setting-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.event-strategy-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.setting-grid label{display:flex;flex-direction:column;gap:6px;padding:10px;border:1px solid var(--nvr-border);border-radius:8px;background:var(--nvr-surface)}.setting-grid label>span{color:var(--nvr-muted);font-size:10px}.setting-grid label>small{min-height:28px;color:var(--nvr-subtle);font-size:9px;line-height:1.5}.zone-section,.zone-editor-card{padding:13px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.zone-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.zone-head>div{display:flex;flex-direction:column;gap:3px}.zone-head strong{font-size:12px}.zone-list{display:flex;flex-direction:column}.zone-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 0;border-top:1px solid var(--nvr-border)}.zone-row:first-child{border-top:0}.zone-row>div:first-child{display:flex;min-width:0;flex-direction:column;gap:3px}.zone-row strong{font-size:11px}.zone-actions{display:flex;align-items:center;gap:5px}.zone-empty{display:flex;flex-direction:column;gap:4px;padding:16px;text-align:center;border:1px dashed var(--nvr-border);border-radius:8px}.zone-empty strong{font-size:11px}.zone-editor-card{display:flex;flex-direction:column;gap:10px}.zone-editor-head{display:grid;grid-template-columns:auto minmax(180px,1fr);align-items:center;gap:12px}.zone-editor-head strong{font-size:12px}.zone-editor-actions{display:flex;justify-content:flex-end;gap:7px}@media(max-width:900px){.event-strategy-grid{grid-template-columns:1fr}}@media(max-width:620px){.setting-grid{grid-template-columns:1fr}.runtime-strip{flex-wrap:wrap}.setting-section-head{align-items:flex-start;flex-direction:column;gap:3px}.zone-row{align-items:flex-start;flex-direction:column}.zone-actions{width:100%;justify-content:flex-end}.zone-editor-head{grid-template-columns:1fr}}
</style>
