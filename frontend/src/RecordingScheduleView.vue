<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

interface RecordingWindow {
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

const loading = ref(false)
const saving = ref(false)
const cameras = ref<Camera[]>([])
const systemStatus = ref<SystemStatus | null>(null)
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)

const form = reactive({
  name: '',
  auto_record: true,
  recording_schedule_enabled: false,
  recording_schedule: [] as RecordingWindow[],
})

const scheduleByCamera = computed(() =>
  new Map((systemStatus.value?.recording_schedule?.cameras || []).map((item) => [item.camera_id, item])),
)

function goBack() { window.location.href = '/' }
function cloneWindows(windows?: RecordingWindow[]) {
  return (windows || []).map((item) => ({ start: item.start, end: item.end }))
}
function scheduleText(camera: Camera) {
  if (!camera.auto_record) return '仅手动'
  if (!camera.recording_schedule_enabled) return '全天自动录像'
  if (!camera.recording_schedule.length) return '未配置时段'
  return camera.recording_schedule.map((item) => `${item.start}-${item.end}`).join('、')
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
function openSchedule(camera: Camera) {
  editingId.value = camera.id
  form.name = camera.name
  form.auto_record = camera.auto_record
  form.recording_schedule_enabled = camera.recording_schedule_enabled
  form.recording_schedule = cloneWindows(camera.recording_schedule)
  if (form.recording_schedule_enabled && !form.recording_schedule.length) addWindow()
  dialogVisible.value = true
}
function addWindow() {
  form.recording_schedule.push({ start: '08:00', end: '18:00' })
}
function removeWindow(index: number) {
  form.recording_schedule.splice(index, 1)
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
    ElMessage.warning('启用录制时段后至少需要一个时间段')
    return false
  }
  for (const item of form.recording_schedule) {
    if (!item.start || !item.end) {
      ElMessage.warning('请完整填写每个时间段的开始和结束时间')
      return false
    }
    if (item.start === item.end) {
      ElMessage.warning('开始时间和结束时间不能相同；全天录像请关闭“启用录制时段”')
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
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '录制时段加载失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (editingId.value === null || !validateWindows()) return
  saving.value = true
  try {
    await axios.put(`/api/cameras/${editingId.value}`, {
      auto_record: form.auto_record,
      recording_schedule_enabled: form.recording_schedule_enabled,
      recording_schedule: cloneWindows(form.recording_schedule),
    })
    dialogVisible.value = false
    ElMessage.success('录制时段已保存，将在 10 秒内按新计划校准')
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
        <h2>录制时段</h2>
        <p>每路摄像头独立计划 · 支持多个时段和跨午夜 · 使用部署服务器本地时区</p>
      </div>
      <div class="actions"><el-button @click="load">刷新</el-button><el-button @click="goBack">返回主界面</el-button></div>
    </div>

    <el-alert type="info" :closable="false" show-icon class="hint">
      <template #title>未启用录制时段时，自动录像保持原来的 24 小时行为。手动开始可以越过时段持续录像；手动停止会暂停当前自动时段，下一时段恢复。</template>
    </el-alert>

    <el-card shadow="never">
      <el-table :data="cameras" empty-text="还没有摄像头">
        <el-table-column prop="name" label="摄像头" min-width="160" />
        <el-table-column prop="ip" label="IP" width="150" />
        <el-table-column label="自动录像" width="110"><template #default="{ row }"><el-tag :type="row.auto_record ? 'success' : 'info'">{{ row.auto_record ? '开启' : '关闭' }}</el-tag></template></el-table-column>
        <el-table-column label="录制计划" min-width="300"><template #default="{ row }">{{ scheduleText(row) }}</template></el-table-column>
        <el-table-column label="当前状态" min-width="180"><template #default="{ row }"><el-tag :type="stateType(row)">{{ stateText(row) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="110" fixed="right"><template #default="{ row }"><el-button size="small" type="primary" @click="openSchedule(row)">设置时段</el-button></template></el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="`${form.name} · 录制时段`" width="640px">
      <el-form label-width="120px">
        <el-form-item label="自动录像"><el-switch v-model="form.auto_record" /><span class="form-hint">关闭后只允许手动开始录像</span></el-form-item>
        <el-form-item label="启用录制时段"><el-switch v-model="form.recording_schedule_enabled" @change="enableSchedule" /><el-button v-if="form.recording_schedule_enabled" link type="primary" @click="useAllDay">改为全天</el-button></el-form-item>
        <template v-if="form.recording_schedule_enabled">
          <el-form-item label="时间段">
            <div class="window-list">
              <div v-for="(item, index) in form.recording_schedule" :key="index" class="window-row">
                <el-time-picker v-model="item.start" format="HH:mm" value-format="HH:mm" :clearable="false" placeholder="开始" />
                <span>至</span>
                <el-time-picker v-model="item.end" format="HH:mm" value-format="HH:mm" :clearable="false" placeholder="结束" />
                <el-button type="danger" plain size="small" @click="removeWindow(index)">删除</el-button>
                <el-tag v-if="item.start && item.end && item.start > item.end" size="small" type="warning">跨午夜</el-tag>
              </div>
              <el-button type="primary" plain size="small" @click="addWindow">+ 添加时间段</el-button>
            </div>
          </el-form-item>
          <el-form-item label="示例"><span class="form-hint no-margin">08:00-12:00 + 14:00-18:00；或 22:00-06:00（跨午夜）</span></el-form-item>
        </template>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
:global(body){margin:0;background:#f5f7fa;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.page-shell{max-width:1500px;margin:0 auto;padding:24px}.page-head{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:16px}.page-head h2{margin:0 0 6px}.page-head p{margin:0;color:#909399}.actions{display:flex;gap:8px}.hint{margin-bottom:16px}.window-list{width:100%;display:flex;flex-direction:column;gap:10px}.window-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.window-row :deep(.el-date-editor){width:150px}.form-hint{margin-left:10px;color:#909399;font-size:12px}.no-margin{margin-left:0}@media(max-width:720px){.page-shell{padding:14px}.page-head{align-items:flex-start;flex-direction:column}.window-row :deep(.el-date-editor){width:125px}}
</style>
