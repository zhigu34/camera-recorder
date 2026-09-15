<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useCameraStore, type RecordingWindow, type SharedCamera } from './stores/cameras'
import { useRuntimeStore } from './stores/runtime'
import { formatDateTime } from './utils/dateTime'

const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
const WORK_DAYS = [0, 1, 2, 3, 4]
const WEEKEND = [5, 6]
const weekdayOptions = [
  { value: 0, label: '周一', short: '一' },
  { value: 1, label: '周二', short: '二' },
  { value: 2, label: '周三', short: '三' },
  { value: 3, label: '周四', short: '四' },
  { value: 4, label: '周五', short: '五' },
  { value: 5, label: '周六', short: '六' },
  { value: 6, label: '周日', short: '日' },
]

const cameraStore = useCameraStore()
const runtime = useRuntimeStore()
const { cameras, loading: cameraLoading } = storeToRefs(cameraStore)
const { systemStatus } = storeToRefs(runtime)
const refreshing = ref(false)
const loading = computed(() => refreshing.value || cameraLoading.value)
const saving = ref(false)
const dialogVisible = ref(false)
const dialogMode = ref<'single' | 'batch'>('single')
const editingId = ref<number | null>(null)
const selectedIds = ref<number[]>([])

const form = reactive({
  name: '',
  auto_record: true,
  recording_schedule_enabled: false,
  recording_schedule: [] as RecordingWindow[],
})

const scheduleByCamera = computed(() =>
  new Map((systemStatus.value?.recording_schedule?.cameras || []).map((item) => [item.camera_id, item])),
)
const dialogTitle = computed(() =>
  dialogMode.value === 'batch'
    ? `批量应用周计划 · ${selectedIds.value.length} 路摄像头`
    : `${form.name} · 周录制计划`,
)
const managerHealthy = computed(() => Boolean(
  systemStatus.value?.recording_schedule?.running && !systemStatus.value?.recording_schedule?.last_error,
))

function normalizedDays(days?: number[]) {
  if (!days?.length) return [...ALL_DAYS]
  return [...new Set(days)].sort((a, b) => a - b)
}

function cloneWindows(windows?: RecordingWindow[]) {
  return (windows || []).map((item) => ({
    days: normalizedDays(item.days),
    start: item.start,
    end: item.end,
  }))
}

function sameDays(days: number[] | undefined, target: number[]) {
  return normalizedDays(days).join(',') === target.join(',')
}

function dayLabel(days?: number[]) {
  const value = normalizedDays(days)
  if (value.join(',') === ALL_DAYS.join(',')) return '每天'
  if (value.join(',') === WORK_DAYS.join(',')) return '周一至周五'
  if (value.join(',') === WEEKEND.join(',')) return '周末'
  return value.map((day) => weekdayOptions.find((item) => item.value === day)?.label || `${day}`).join('/')
}

function crossesMidnight(item: RecordingWindow) {
  return Boolean(item.start && item.end && item.start > item.end)
}

function windowDurationLabel(item: RecordingWindow) {
  const parse = (value: string) => {
    const [hours, minutes] = value.split(':').map(Number)
    return Number.isFinite(hours) && Number.isFinite(minutes) ? hours * 60 + minutes : null
  }
  const start = parse(item.start)
  const end = parse(item.end)
  if (start === null || end === null || start === end) return '—'
  let duration = end - start
  if (duration < 0) duration += 24 * 60
  const hours = Math.floor(duration / 60)
  const minutes = duration % 60
  if (!hours) return `${minutes} 分钟`
  return `${hours} 小时${minutes ? ` ${minutes} 分` : ''}`
}

function scheduleText(camera: SharedCamera) {
  const schedule = camera.recording_schedule || []
  if (!camera.auto_record) return camera.recording_schedule_enabled ? '周计划已配置 · 自动录像关闭' : '仅手动'
  if (!camera.recording_schedule_enabled) return '全天自动录像'
  if (!schedule.length) return '未配置时段'
  return schedule.map((item) => `${dayLabel(item.days)} ${item.start}-${item.end}`).join('；')
}

function stateText(camera: SharedCamera) {
  const runtimeState = scheduleByCamera.value.get(camera.id)
  if (!camera.enabled) return '已禁用'
  if (!camera.auto_record) return runtimeState?.running ? '手动录像中' : '仅手动'
  const state = runtimeState?.schedule_state
  if (state === 'global_disabled') return '全局自动录像已关闭'
  if (state === 'automatic') return runtimeState?.running ? '全天录像中' : '等待自动启动'
  if (state === 'scheduled') return '等待录制时段'
  if (state === 'in_window') return runtimeState?.running ? '时段内录像中' : '时段内等待启动'
  if (state === 'manual_override') return '手动覆盖录像中'
  if (state === 'manual_paused') return '当前时段已手动暂停'
  if (state === 'probe_required') return '需要先检测媒体参数'
  if (state === 'error') return '计划启动失败'
  if (runtimeState?.running) return '录像中'
  return '待命'
}

function stateType(camera: SharedCamera) {
  const runtimeState = scheduleByCamera.value.get(camera.id)
  if (!camera.enabled || !camera.auto_record) return 'info'
  if (runtimeState?.schedule_state === 'error') return 'danger'
  if (runtimeState?.schedule_state === 'probe_required' || runtimeState?.schedule_state === 'manual_paused') return 'warning'
  if (runtimeState?.running) return 'success'
  if (runtimeState?.schedule_state === 'in_window') return 'warning'
  return 'info'
}

function applyCameraToForm(camera: SharedCamera) {
  form.name = camera.name
  form.recording_schedule_enabled = Boolean(camera.recording_schedule_enabled)
  // Repair the legacy contradictory combination in the editor. A weekly schedule
  // is an automatic-recording policy, so opening an existing scheduled camera
  // should present auto recording as enabled and saving will persist that repair.
  form.auto_record = camera.recording_schedule_enabled ? true : Boolean(camera.auto_record)
  form.recording_schedule = cloneWindows(camera.recording_schedule)
  if (form.recording_schedule_enabled && !form.recording_schedule.length) addWindow()
}

function openSchedule(camera: SharedCamera) {
  dialogMode.value = 'single'
  editingId.value = camera.id
  applyCameraToForm(camera)
  dialogVisible.value = true
}

function openBatchSchedule() {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先选择要批量应用的摄像头')
    return
  }
  const first = cameras.value.find((camera) => camera.id === selectedIds.value[0])
  dialogMode.value = 'batch'
  editingId.value = null
  if (first) applyCameraToForm(first)
  else {
    form.name = ''
    form.auto_record = true
    form.recording_schedule_enabled = true
    form.recording_schedule = [{ days: [...WORK_DAYS], start: '08:00', end: '18:00' }]
  }
  dialogVisible.value = true
}

function onSelectionChange(rows: SharedCamera[]) {
  selectedIds.value = rows.map((item) => item.id)
}

function addWindow() { form.recording_schedule.push({ days: [...ALL_DAYS], start: '08:00', end: '18:00' }) }
function removeWindow(index: number) { form.recording_schedule.splice(index, 1) }
function setWindowDays(index: number, days: number[]) { form.recording_schedule[index].days = [...days] }
function toggleWindowDay(index: number, day: number) {
  const days = form.recording_schedule[index].days
  form.recording_schedule[index].days = days.includes(day)
    ? days.filter((value) => value !== day)
    : [...days, day].sort((a, b) => a - b)
}
function useAllDay() { form.recording_schedule_enabled = false }
function setAutoRecord(value: boolean) {
  form.auto_record = value
  if (!value && form.recording_schedule_enabled) {
    form.recording_schedule_enabled = false
    ElMessage.info('已关闭周计划；周计划需要自动录像开启后才能执行')
  }
}
function enableSchedule(value: boolean) {
  if (!value) return
  if (!form.auto_record) {
    form.auto_record = true
    ElMessage.info('启用周计划已同时开启自动录像')
  }
  if (!form.recording_schedule.length) addWindow()
}

function validateWindows() {
  if (!form.recording_schedule_enabled) return true
  if (!form.recording_schedule.length) {
    ElMessage.warning('启用周计划后至少需要一个时间段')
    return false
  }
  for (const item of form.recording_schedule) {
    if (!item.days.length) {
      ElMessage.warning('每个时间段至少选择一个星期')
      return false
    }
    if (!item.start || !item.end) {
      ElMessage.warning('请完整填写每个时间段的开始和结束时间')
      return false
    }
    if (item.start === item.end) {
      ElMessage.warning('开始时间和结束时间不能相同；全天录像请关闭“启用周计划”')
      return false
    }
  }
  return true
}

async function load(force = false) {
  refreshing.value = true
  try {
    await Promise.all([cameraStore.load(force), runtime.refreshSystem()])
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '录制计划加载失败')
  } finally {
    refreshing.value = false
  }
}

async function save() {
  if (!validateWindows()) return
  saving.value = true
  const scheduleEnabled = form.auto_record && form.recording_schedule_enabled
  const payload = {
    auto_record: scheduleEnabled ? true : form.auto_record,
    recording_schedule_enabled: scheduleEnabled,
    recording_schedule: cloneWindows(form.recording_schedule),
  }
  try {
    if (dialogMode.value === 'batch') {
      await axios.put('/api/cameras/recording-schedule/batch', { ...payload, camera_ids: selectedIds.value })
      ElMessage.success(`周计划已批量应用到 ${selectedIds.value.length} 路摄像头`)
    } else if (editingId.value !== null) {
      await axios.put(`/api/cameras/${editingId.value}`, payload)
      ElMessage.success('周计划已保存并立即重新校准')
    }
    dialogVisible.value = false
    cameraStore.invalidate()
    await load(true)
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => void load(false))
</script>

<template>
  <section class="schedule-page" v-loading="loading">
    <el-alert type="info" :closable="false" show-icon class="hint">
      <template #title>显式周计划从实际开始时间按切片时长分段；全天自动录像保持全局时钟对齐。跨午夜时段归属于开始日，例如“周五 22:00-06:00”会持续到周六 06:00。</template>
    </el-alert>

    <div class="toolbar">
      <div class="manager-state">
        <span class="state-dot" :class="{ ok: managerHealthy }"></span>
        <span>{{ managerHealthy ? '调度器运行中' : '调度器需要关注' }}</span>
        <small v-if="systemStatus?.recording_schedule?.last_check_at">最近校准 {{ formatDateTime(systemStatus.recording_schedule.last_check_at) }}</small>
      </div>
      <div class="toolbar-actions">
        <span class="selected-note">已选择 {{ selectedIds.length }} 路</span>
        <el-button :icon="Refresh" @click="load(true)">刷新</el-button>
        <el-button type="primary" :disabled="!selectedIds.length" @click="openBatchSchedule">批量应用周计划</el-button>
      </div>
    </div>

    <div class="table-shell">
      <el-table :data="cameras" empty-text="还没有摄像头" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="name" label="摄像头" min-width="150" />
        <el-table-column prop="ip" label="IP" width="145" />
        <el-table-column label="自动录像" width="105"><template #default="{ row }"><el-tag :type="row.auto_record ? 'success' : 'info'">{{ row.auto_record ? '开启' : '关闭' }}</el-tag></template></el-table-column>
        <el-table-column label="周计划" min-width="430"><template #default="{ row }"><span class="schedule-cell">{{ scheduleText(row) }}</span></template></el-table-column>
        <el-table-column label="调度状态" min-width="190"><template #default="{ row }"><el-tag :type="stateType(row)">{{ stateText(row) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="120" fixed="right"><template #default="{ row }"><el-button size="small" type="primary" @click="openSchedule(row)">设置周计划</el-button></template></el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="min(920px, 94vw)" class="schedule-dialog">
      <el-alert v-if="dialogMode === 'batch'" type="warning" :closable="false" show-icon class="dialog-alert" title="批量应用会覆盖所有选中摄像头的自动录像开关和整套周计划。" />

      <div class="policy-grid">
        <div class="policy-card" :class="{ active: form.auto_record }">
          <div class="policy-copy"><strong>自动录像</strong><span>周计划依赖此开关；关闭后只允许手动开始录像</span></div>
          <el-switch v-model="form.auto_record" @change="setAutoRecord" />
        </div>
        <div class="policy-card" :class="{ active: form.recording_schedule_enabled }">
          <div class="policy-copy"><strong>周计划模式</strong><span>{{ form.recording_schedule_enabled ? '只在指定时间窗口自动录像' : '全天自动录像' }}</span></div>
          <div class="policy-action"><el-button v-if="form.recording_schedule_enabled" link type="primary" @click="useAllDay">改为全天</el-button><el-switch v-model="form.recording_schedule_enabled" @change="enableSchedule" /></div>
        </div>
      </div>

      <div v-if="form.recording_schedule_enabled" class="schedule-editor">
        <div class="editor-head"><div><strong>录制时间窗口</strong><span>每个窗口可独立选择星期和起止时间，支持跨午夜。</span></div><el-button type="primary" plain size="small" @click="addWindow">+ 新增时间段</el-button></div>
        <div class="window-list">
          <article v-for="(item, index) in form.recording_schedule" :key="index" class="window-card" :class="{ overnight: crossesMidnight(item) }">
            <div class="window-card-head">
              <div class="window-title"><span class="window-number">{{ String(index + 1).padStart(2, '0') }}</span><div><strong>时间窗口 {{ index + 1 }}</strong><small>{{ dayLabel(item.days) }} · {{ item.start }} → {{ item.end }}</small></div></div>
              <div class="window-head-actions"><span v-if="crossesMidnight(item)" class="overnight-badge">跨午夜</span><button class="delete-window" type="button" @click="removeWindow(index)">删除</button></div>
            </div>
            <div class="window-section">
              <div class="section-title"><strong>生效日期</strong><span>点击星期即可切换</span></div>
              <div class="preset-row"><button type="button" :class="{ active: sameDays(item.days, ALL_DAYS) }" @click="setWindowDays(index, ALL_DAYS)">每天</button><button type="button" :class="{ active: sameDays(item.days, WORK_DAYS) }" @click="setWindowDays(index, WORK_DAYS)">工作日</button><button type="button" :class="{ active: sameDays(item.days, WEEKEND) }" @click="setWindowDays(index, WEEKEND)">周末</button></div>
              <div class="weekday-grid"><button v-for="day in weekdayOptions" :key="day.value" type="button" :class="{ active: item.days.includes(day.value) }" :title="day.label" @click="toggleWindowDay(index, day.value)"><span>{{ day.short }}</span><small>{{ day.label }}</small></button></div>
            </div>
            <div class="time-band">
              <div class="time-field"><span class="time-label">开始时间</span><el-time-picker v-model="item.start" format="HH:mm" value-format="HH:mm" :clearable="false" placeholder="开始" /></div>
              <div class="time-bridge"><span>→</span><small>{{ crossesMidnight(item) ? '次日结束' : '当日结束' }}</small></div>
              <div class="time-field"><span class="time-label">结束时间</span><el-time-picker v-model="item.end" format="HH:mm" value-format="HH:mm" :clearable="false" placeholder="结束" /></div>
              <div class="duration-box"><strong>{{ windowDurationLabel(item) }}</strong><span>持续时长</span></div>
            </div>
            <div class="window-note" :class="{ overnight: crossesMidnight(item) }"><i></i><span v-if="crossesMidnight(item)">从 {{ item.start }} 开始录像，并在次日 {{ item.end }} 结束；该窗口归属于开始日。</span><span v-else>{{ item.start }} 至 {{ item.end }} 在所选日期内完成。</span></div>
          </article>
        </div>
        <button class="add-window-tile" type="button" @click="addWindow"><span>＋</span><strong>添加另一个时间窗口</strong><small>例如周末使用不同录像时间</small></button>
        <div class="schedule-example"><strong>示例</strong><span>工作日 08:00-18:00 · 周末 09:00-12:00 · 周五 22:00-06:00（跨到周六）</span></div>
      </div>

      <div v-else class="all-day-state"><div class="all-day-icon">24</div><div><strong>{{ form.auto_record ? '全天自动录像' : '仅手动录像' }}</strong><span>{{ form.auto_record ? '周计划未启用，自动录像摄像头将按全天策略运行。' : '自动录像已关闭；启用周计划时会自动重新开启。' }}</span></div></div>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">{{ dialogMode === 'batch' ? '批量应用' : '保存计划' }}</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.schedule-page{max-width:1500px;margin:0 auto;padding:22px;color:var(--nvr-text)}
.hint{margin-bottom:14px}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:10px;padding:10px 12px;border:1px solid var(--nvr-border);border-radius:9px;background:rgba(20,26,34,.72)}.manager-state,.toolbar-actions{display:flex;align-items:center;gap:8px}.manager-state{color:var(--nvr-muted);font-size:11px}.manager-state small{color:#657488}.state-dot{width:7px;height:7px;border-radius:50%;background:var(--nvr-red)}.state-dot.ok{background:var(--nvr-green);box-shadow:0 0 0 3px rgba(46,204,138,.08)}.selected-note{color:var(--nvr-muted);font-size:11px}.table-shell{overflow:hidden;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.schedule-cell{line-height:1.65}.dialog-alert{margin-bottom:14px}
.policy-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:16px}.policy-card{min-width:0;display:flex;align-items:center;justify-content:space-between;gap:14px;padding:13px 14px;border:1px solid var(--nvr-border);border-radius:10px;background:#0f151c;transition:.15s}.policy-card.active{border-color:rgba(76,141,255,.34);background:linear-gradient(135deg,rgba(76,141,255,.09),rgba(76,141,255,.025))}.policy-copy{min-width:0;display:flex;flex-direction:column;gap:4px}.policy-copy strong{font-size:12px;color:#dfe7f0}.policy-copy span{color:var(--nvr-muted);font-size:10px}.policy-action{display:flex;align-items:center;gap:6px}
.schedule-editor{padding-top:2px}.editor-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;margin:4px 0 10px}.editor-head>div{display:flex;flex-direction:column;gap:4px}.editor-head strong{font-size:12px;color:#dce5ee}.editor-head span{color:var(--nvr-muted);font-size:10px}.window-list{display:flex;flex-direction:column;gap:10px}.window-card{overflow:hidden;border:1px solid var(--nvr-border);border-radius:11px;background:linear-gradient(180deg,rgba(255,255,255,.018),transparent 120px),#0d131a;box-shadow:0 8px 28px rgba(0,0,0,.08)}.window-card.overnight{border-color:rgba(230,187,104,.28)}.window-card-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 13px;border-bottom:1px solid rgba(255,255,255,.055);background:rgba(255,255,255,.012)}.window-title{display:flex;align-items:center;gap:10px;min-width:0}.window-number{width:29px;height:29px;display:grid;place-items:center;flex:0 0 auto;border:1px solid rgba(76,141,255,.22);border-radius:8px;color:#78a8ff;background:rgba(76,141,255,.08);font-size:9px;font-weight:800}.window-title>div{min-width:0;display:flex;flex-direction:column;gap:2px}.window-title strong{color:#e1e8f0;font-size:11px}.window-title small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#718095;font-size:9px}.window-head-actions{display:flex;align-items:center;gap:8px}.overnight-badge{padding:3px 6px;border:1px solid rgba(230,187,104,.22);border-radius:999px;color:#e6bb68;background:rgba(230,187,104,.08);font-size:8px;font-weight:700}.delete-window{padding:4px 6px;border:0;color:#8e5d63;background:transparent;cursor:pointer;font-size:9px}.delete-window:hover{color:#f08b8c}
.window-section{padding:12px 13px 11px}.section-title{display:flex;align-items:center;gap:7px;margin-bottom:9px}.section-title strong{color:#aeb9c6;font-size:10px}.section-title span{color:#566579;font-size:9px}.preset-row{display:flex;gap:5px;margin-bottom:8px}.preset-row button{height:24px;padding:0 9px;border:1px solid var(--nvr-border);border-radius:6px;color:#7f8da0;background:#10171f;cursor:pointer;font-size:9px}.preset-row button:hover{border-color:rgba(76,141,255,.35);color:#a9c6fa}.preset-row button.active{border-color:rgba(76,141,255,.42);color:#a9c9ff;background:rgba(76,141,255,.11)}.weekday-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:5px}.weekday-grid button{min-width:0;height:43px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;border:1px solid var(--nvr-border);border-radius:7px;color:#657488;background:#0b1016;cursor:pointer;transition:.15s}.weekday-grid button:hover{border-color:rgba(76,141,255,.35);color:#a8b7c8}.weekday-grid button.active{border-color:rgba(76,141,255,.5);color:#dce9ff;background:linear-gradient(180deg,rgba(76,141,255,.17),rgba(76,141,255,.075));box-shadow:inset 0 0 0 1px rgba(76,141,255,.06)}.weekday-grid button>span{font-size:12px;font-weight:800}.weekday-grid button small{font-size:8px;color:inherit;opacity:.72}
.time-band{display:grid;grid-template-columns:minmax(150px,1fr) 64px minmax(150px,1fr) 120px;gap:10px;align-items:end;padding:12px 13px;border-top:1px solid rgba(255,255,255,.05);background:#0a1016}.time-field{min-width:0;display:flex;flex-direction:column;gap:5px}.time-label{color:#657488;font-size:9px}.time-field :deep(.el-date-editor){width:100%!important}.time-field :deep(.el-input__wrapper){min-height:38px;border-radius:7px;background:#10171f;box-shadow:0 0 0 1px var(--nvr-border) inset}.time-field :deep(.el-input__inner){font-size:14px;font-weight:700;letter-spacing:.04em}.time-bridge{height:38px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0;color:#5d6d81}.time-bridge>span{font-size:18px;line-height:15px}.time-bridge small{font-size:8px;white-space:nowrap}.duration-box{height:38px;display:flex;flex-direction:column;justify-content:center;gap:1px;padding:0 9px;border:1px solid var(--nvr-border);border-radius:7px;background:#10171f}.duration-box strong{color:#b9c7d7;font-size:11px}.duration-box span{color:#59687b;font-size:8px}.window-note{display:flex;align-items:center;gap:6px;padding:8px 13px;border-top:1px solid rgba(255,255,255,.04);color:#5e6e81;background:#0d131a;font-size:9px}.window-note i{width:5px;height:5px;flex:0 0 auto;border-radius:50%;background:var(--nvr-green)}.window-note.overnight{color:#9c8558;background:rgba(230,187,104,.025)}.window-note.overnight i{background:#e6bb68}
.add-window-tile{width:100%;min-height:54px;margin-top:10px;display:flex;align-items:center;justify-content:center;gap:8px;border:1px dashed rgba(76,141,255,.25);border-radius:9px;color:#7188a5;background:rgba(76,141,255,.025);cursor:pointer}.add-window-tile:hover{border-color:rgba(76,141,255,.48);color:#9cbef5;background:rgba(76,141,255,.055)}.add-window-tile>span{font-size:17px}.add-window-tile strong{font-size:10px}.add-window-tile small{color:#526174;font-size:8px}.schedule-example{display:flex;gap:8px;margin-top:9px;padding:8px 10px;border-radius:7px;color:#59687b;background:rgba(255,255,255,.018);font-size:9px}.schedule-example strong{color:#718095;white-space:nowrap}.all-day-state{display:flex;align-items:center;gap:12px;padding:18px;border:1px solid rgba(46,204,138,.16);border-radius:11px;background:linear-gradient(135deg,rgba(46,204,138,.06),rgba(46,204,138,.015))}.all-day-icon{width:42px;height:42px;display:grid;place-items:center;flex:0 0 auto;border-radius:10px;color:#86dcb3;background:rgba(46,204,138,.1);font-size:15px;font-weight:800}.all-day-state>div:last-child{display:flex;flex-direction:column;gap:4px}.all-day-state strong{color:#d8e7df;font-size:12px}.all-day-state span{color:#66788a;font-size:10px}
@media(max-width:760px){.schedule-page{padding:14px}.toolbar{align-items:stretch;flex-direction:column}.manager-state,.toolbar-actions{flex-wrap:wrap}.policy-grid{grid-template-columns:1fr}.window-card-head{align-items:flex-start}.window-head-actions{flex-direction:column;align-items:flex-end}.weekday-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.time-band{grid-template-columns:1fr 42px 1fr}.duration-box{grid-column:1 / -1}.add-window-tile{flex-wrap:wrap;padding:9px}.schedule-example{align-items:flex-start}.schedule-example span{line-height:1.5}}
</style>