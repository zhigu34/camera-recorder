<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

interface RecordingWindow {
  days: number[]
  start: string
  end: string
}

interface Camera {
  id: number
  name: string
  ip: string
  enabled: boolean
  auto_record: boolean
  recording_schedule_enabled: boolean
  recording_schedule: RecordingWindow[]
}

interface ScheduleRuntime {
  camera_id: number
  schedule_enabled: boolean
  schedule: string
  in_window: boolean
  auto_eligible: boolean
  running: boolean
  mode: string
}

interface SystemStatus {
  recording_schedule?: {
    running: boolean
    poll_interval_seconds: number
    last_check_at?: string | null
    cameras: ScheduleRuntime[]
  }
}

const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
const WORK_DAYS = [0, 1, 2, 3, 4]
const WEEKEND = [5, 6]
const weekdayOptions = [
  { value: 0, label: '周一' },
  { value: 1, label: '周二' },
  { value: 2, label: '周三' },
  { value: 3, label: '周四' },
  { value: 4, label: '周五' },
  { value: 5, label: '周六' },
  { value: 6, label: '周日' },
]

const loading = ref(false)
const saving = ref(false)
const cameras = ref<Camera[]>([])
const systemStatus = ref<SystemStatus | null>(null)
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

function goBack() { window.location.href = '/' }
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
function dayLabel(days?: number[]) {
  const value = normalizedDays(days)
  if (value.join(',') === ALL_DAYS.join(',')) return '每天'
  if (value.join(',') === WORK_DAYS.join(',')) return '周一至周五'
  if (value.join(',') === WEEKEND.join(',')) return '周末'
  return value.map((day) => weekdayOptions.find((item) => item.value === day)?.label || `${day}`).join('/')
}
function scheduleText(camera: Camera) {
  if (!camera.auto_record) return '仅手动'
  if (!camera.recording_schedule_enabled) return '全天自动录像'
  if (!camera.recording_schedule.length) return '未配置时段'
  return camera.recording_schedule
    .map((item) => `${dayLabel(item.days)} ${item.start}-${item.end}`)
    .join('；')
}
function stateText(camera: Camera) {
  const runtime = scheduleByCamera.value.get(camera.id)
  if (!camera.enabled) return '已禁用'
  if (!camera.auto_record) return runtime?.running ? '手动录像中' : '仅手动'
  if (!camera.recording_schedule_enabled) return runtime?.running ? '全天录像中' : '等待自动启动'
  if (runtime?.mode === 'manual') return '手动覆盖录像中'
  if (runtime?.mode === 'manual_paused') return '当前时段已手动暂停'
  if (runtime?.in_window) return runtime.running ? '时段内录像中' : '时段内等待启动'
  return '等待录制时段'
}
function stateType(camera: Camera) {
  const runtime = scheduleByCamera.value.get(camera.id)
  if (!camera.enabled || !camera.auto_record) return 'info'
  if (runtime?.running) return 'success'
  if (runtime?.in_window) return 'warning'
  return 'info'
}
function applyCameraToForm(camera: Camera) {
  form.name = camera.name
  form.auto_record = camera.auto_record
  form.recording_schedule_enabled = camera.recording_schedule_enabled
  form.recording_schedule = cloneWindows(camera.recording_schedule)
  if (form.recording_schedule_enabled && !form.recording_schedule.length) addWindow()
}
function openSchedule(camera: Camera) {
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
function onSelectionChange(rows: Camera[]) {
  selectedIds.value = rows.map((item) => item.id)
}
function addWindow() {
  form.recording_schedule.push({ days: [...ALL_DAYS], start: '08:00', end: '18:00' })
}
function removeWindow(index: number) {
  form.recording_schedule.splice(index, 1)
}
function setWindowDays(index: number, days: number[]) {
  form.recording_schedule[index].days = [...days]
}
function useAllDay() {
  form.recording_schedule_enabled = false
}
function enableSchedule(value: boolean) {
  if (value && !form.recording_schedule.length) addWindow()
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

async function load() {
  loading.value = true
  try {
    const [cameraRes, statusRes] = await Promise.all([
      axios.get<Camera[]>('/api/cameras'),
      axios.get<SystemStatus>('/api/system/status'),
    ])
    cameras.value = cameraRes.data
    systemStatus.value = statusRes.data
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '录制计划加载失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!validateWindows()) return
  saving.value = true
  const payload = {
    auto_record: form.auto_record,
    recording_schedule_enabled: form.recording_schedule_enabled,
    recording_schedule: cloneWindows(form.recording_schedule),
  }
  try {
    if (dialogMode.value === 'batch') {
      await axios.put('/api/cameras/recording-schedule/batch', {
        ...payload,
        camera_ids: selectedIds.value,
      })
      ElMessage.success(`周计划已批量应用到 ${selectedIds.value.length} 路摄像头`)
    } else if (editingId.value !== null) {
      await axios.put(`/api/cameras/${editingId.value}`, payload)
      ElMessage.success('周计划已保存并立即重新校准')
    }
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-shell" v-loading="loading">
    <div class="page-head">
      <div>
        <h2>录制周计划</h2>
        <p>每路摄像头独立计划 · 支持星期、多时段、跨午夜和批量应用 · 使用部署服务器本地时区</p>
      </div>
      <div class="actions"><el-button @click="load">刷新</el-button><el-button @click="goBack">返回主界面</el-button></div>
    </div>

    <el-alert type="info" :closable="false" show-icon class="hint">
      <template #title>显式周计划从实际开始时间按 10 分钟切片，不再强制对齐 00/10/20 分钟边界；全天自动录像仍保持原来的整点切片。跨午夜时段归属于开始日，例如“周五 22:00-06:00”会持续到周六 06:00。</template>
    </el-alert>

    <div class="toolbar">
      <span class="selected-note">已选择 {{ selectedIds.length }} 路</span>
      <el-button type="primary" :disabled="!selectedIds.length" @click="openBatchSchedule">批量应用周计划</el-button>
    </div>

    <el-card shadow="never">
      <el-table :data="cameras" empty-text="还没有摄像头" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="name" label="摄像头" min-width="150" />
        <el-table-column prop="ip" label="IP" width="145" />
        <el-table-column label="自动录像" width="105"><template #default="{ row }"><el-tag :type="row.auto_record ? 'success' : 'info'">{{ row.auto_record ? '开启' : '关闭' }}</el-tag></template></el-table-column>
        <el-table-column label="周计划" min-width="430"><template #default="{ row }"><span class="schedule-cell">{{ scheduleText(row) }}</span></template></el-table-column>
        <el-table-column label="当前状态" min-width="180"><template #default="{ row }"><el-tag :type="stateType(row)">{{ stateText(row) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="120" fixed="right"><template #default="{ row }"><el-button size="small" type="primary" @click="openSchedule(row)">设置周计划</el-button></template></el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="820px">
      <el-alert v-if="dialogMode === 'batch'" type="warning" :closable="false" show-icon class="dialog-alert" title="批量应用会覆盖所有选中摄像头的自动录像开关和整套周计划。" />
      <el-form label-width="120px">
        <el-form-item label="自动录像"><el-switch v-model="form.auto_record" /><span class="form-hint">关闭后只允许手动开始录像</span></el-form-item>
        <el-form-item label="启用周计划"><el-switch v-model="form.recording_schedule_enabled" @change="enableSchedule" /><el-button v-if="form.recording_schedule_enabled" link type="primary" @click="useAllDay">改为全天</el-button></el-form-item>
        <template v-if="form.recording_schedule_enabled">
          <el-form-item label="时间段">
            <div class="window-list">
              <div v-for="(item, index) in form.recording_schedule" :key="index" class="window-card">
                <div class="window-days">
                  <el-select v-model="item.days" multiple collapse-tags collapse-tags-tooltip placeholder="选择星期" style="width: 260px">
                    <el-option v-for="day in weekdayOptions" :key="day.value" :label="day.label" :value="day.value" />
                  </el-select>
                  <el-button size="small" @click="setWindowDays(index, ALL_DAYS)">每天</el-button>
                  <el-button size="small" @click="setWindowDays(index, WORK_DAYS)">工作日</el-button>
                  <el-button size="small" @click="setWindowDays(index, WEEKEND)">周末</el-button>
                </div>
                <div class="window-time">
                  <el-time-picker v-model="item.start" format="HH:mm" value-format="HH:mm" :clearable="false" placeholder="开始" />
                  <span>至</span>
                  <el-time-picker v-model="item.end" format="HH:mm" value-format="HH:mm" :clearable="false" placeholder="结束" />
                  <el-tag v-if="item.start && item.end && item.start > item.end" size="small" type="warning">跨午夜</el-tag>
                  <el-button type="danger" plain size="small" @click="removeWindow(index)">删除</el-button>
                </div>
                <div class="window-summary">{{ dayLabel(item.days) }} · {{ item.start }}-{{ item.end }}</div>
              </div>
              <el-button type="primary" plain size="small" @click="addWindow">+ 添加时间段</el-button>
            </div>
          </el-form-item>
          <el-form-item label="示例"><span class="form-hint no-margin">周一至周五 08:00-18:00；周末 09:00-12:00；周五 22:00-06:00（跨到周六）</span></el-form-item>
        </template>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">{{ dialogMode === 'batch' ? '批量应用' : '保存' }}</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
:global(body){margin:0;background:#f5f7fa;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.page-shell{max-width:1500px;margin:0 auto;padding:24px}.page-head{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:16px}.page-head h2{margin:0 0 6px}.page-head p{margin:0;color:#909399}.actions,.toolbar{display:flex;align-items:center;gap:8px}.hint{margin-bottom:16px}.toolbar{justify-content:flex-end;margin-bottom:12px}.selected-note{font-size:13px;color:#909399}.schedule-cell{line-height:1.65}.dialog-alert{margin-bottom:16px}.window-list{width:100%;display:flex;flex-direction:column;gap:12px}.window-card{padding:12px;border:1px solid #ebeef5;border-radius:8px;background:#fafafa}.window-days,.window-time{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.window-time{margin-top:10px}.window-time :deep(.el-date-editor){width:150px}.window-summary{margin-top:8px;color:#909399;font-size:12px}.form-hint{margin-left:10px;color:#909399;font-size:12px}.no-margin{margin-left:0}@media(max-width:720px){.page-shell{padding:14px}.page-head{align-items:flex-start;flex-direction:column}.window-time :deep(.el-date-editor){width:125px}.window-days :deep(.el-select){width:100%!important}}
</style>
