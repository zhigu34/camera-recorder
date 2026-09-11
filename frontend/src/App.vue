<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

interface Camera {
  id: number
  name: string
  ip: string
  rtsp_port: number
  username: string
  rtsp_path: string
  enabled: boolean
  auto_record: boolean
  timestamp_mode: string
  video_codec?: string | null
  width?: number | null
  height?: number | null
  fps_num?: number | null
  fps_den?: number | null
  audio_codec?: string | null
  sample_rate?: number | null
  channels?: number | null
  status: string
}

interface Recording {
  id: number
  camera_id: number
  started_at?: string | null
  duration?: number | null
  file_size?: number | null
  health_status: string
  upload_status: string
  mp4_path: string
}

interface SystemStatus {
  app: string
  segment_duration_seconds: number
  ffmpeg: {
    ffmpeg_available: boolean
    ffprobe_available: boolean
    setts_available: boolean
    ffmpeg_version?: string | null
  }
  recorders: Array<{ camera_id: number; state: string; pid?: number | null }>
}

const page = ref('dashboard')
const loading = ref(false)
const cameras = ref<Camera[]>([])
const recordings = ref<Recording[]>([])
const status = ref<SystemStatus | null>(null)
const dialogVisible = ref(false)
const saving = ref(false)

const form = reactive({
  name: '',
  ip: '',
  rtsp_port: 554,
  username: 'admin',
  password: '',
  rtsp_path: '/ch1/main',
  timestamp_mode: 'reconstruct',
  enabled: true,
  auto_record: false,
})

const recordingCount = computed(() =>
  cameras.value.filter((camera) => runtimeState(camera.id) === 'RECORDING').length,
)

function runtimeState(cameraId: number) {
  return status.value?.recorders.find((item) => item.camera_id === cameraId)?.state || 'STOPPED'
}

function fps(camera: Camera) {
  if (!camera.fps_num || !camera.fps_den) return '-'
  const value = camera.fps_num / camera.fps_den
  return Number.isInteger(value) ? `${value}` : value.toFixed(2)
}

function sizeText(bytes?: number | null) {
  if (!bytes) return '-'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

async function loadAll() {
  loading.value = true
  try {
    const [systemRes, cameraRes, recordingRes] = await Promise.all([
      axios.get<SystemStatus>('/api/system/status'),
      axios.get<Camera[]>('/api/cameras'),
      axios.get<Recording[]>('/api/recordings?limit=100'),
    ])
    status.value = systemRes.data
    cameras.value = cameraRes.data
    recordings.value = recordingRes.data
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function createCamera() {
  saving.value = true
  try {
    await axios.post('/api/cameras', form)
    ElMessage.success('摄像头已添加')
    dialogVisible.value = false
    Object.assign(form, {
      name: '', ip: '', rtsp_port: 554, username: 'admin', password: '',
      rtsp_path: '/ch1/main', timestamp_mode: 'reconstruct', enabled: true, auto_record: false,
    })
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '添加失败')
  } finally {
    saving.value = false
  }
}

async function probe(camera: Camera) {
  try {
    const { data } = await axios.post(`/api/cameras/${camera.id}/probe`)
    ElMessage.success(`${camera.name}: ${data.video_codec || '-'} ${data.width || '-'}×${data.height || '-'} / ${data.fps?.toFixed?.(2) || '-'}fps`)
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : 'Probe 失败')
  }
}

async function start(camera: Camera) {
  try {
    await axios.post(`/api/cameras/${camera.id}/start`)
    ElMessage.success(`${camera.name} 已开始录像`)
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '启动失败')
  }
}

async function stop(camera: Camera) {
  try {
    await axios.post(`/api/cameras/${camera.id}/stop`)
    ElMessage.success(`${camera.name} 已停止`)
    await loadAll()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '停止失败')
  }
}

async function remove(camera: Camera) {
  await ElMessageBox.confirm(`确认删除 ${camera.name}？`, '删除摄像头', { type: 'warning' })
  await axios.delete(`/api/cameras/${camera.id}`)
  ElMessage.success('已删除')
  await loadAll()
}

async function startAll() {
  await axios.post('/api/recorder/start-all')
  ElMessage.success('已启动可录像摄像头')
  await loadAll()
}

async function stopAll() {
  await axios.post('/api/recorder/stop-all')
  ElMessage.success('已停止全部录像')
  await loadAll()
}

onMounted(loadAll)
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="210px" class="sidebar">
      <div class="brand">Camera Recorder</div>
      <el-menu :default-active="page" @select="page = $event">
        <el-menu-item index="dashboard">仪表盘</el-menu-item>
        <el-menu-item index="cameras">摄像头</el-menu-item>
        <el-menu-item index="recordings">录像文件</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div>
          <strong>{{ page === 'dashboard' ? '仪表盘' : page === 'cameras' ? '摄像头管理' : '录像文件' }}</strong>
          <span class="subtitle">RTSP 长连接 · H.265/AAC 原码流</span>
        </div>
        <div class="header-actions">
          <el-button @click="loadAll">刷新</el-button>
          <el-button type="success" @click="startAll">全部开始</el-button>
          <el-button type="danger" plain @click="stopAll">全部停止</el-button>
        </div>
      </el-header>

      <el-main v-loading="loading">
        <template v-if="page === 'dashboard'">
          <el-row :gutter="16">
            <el-col :span="6"><el-card><div class="metric">{{ cameras.length }}</div><div class="muted">摄像头</div></el-card></el-col>
            <el-col :span="6"><el-card><div class="metric">{{ recordingCount }}</div><div class="muted">录像中</div></el-card></el-col>
            <el-col :span="6"><el-card><div class="metric">{{ recordings.length }}</div><div class="muted">最近录像</div></el-card></el-col>
            <el-col :span="6">
              <el-card>
                <el-tag :type="status?.ffmpeg.setts_available ? 'success' : 'danger'">
                  {{ status?.ffmpeg.setts_available ? 'setts 可用' : 'setts 不可用' }}
                </el-tag>
                <div class="muted top-gap">切片 {{ status?.segment_duration_seconds || '-' }} 秒</div>
              </el-card>
            </el-col>
          </el-row>

          <el-card class="section-card">
            <template #header>摄像头状态</template>
            <el-table :data="cameras" empty-text="还没有摄像头">
              <el-table-column prop="name" label="名称" min-width="150" />
              <el-table-column prop="ip" label="IP" width="150" />
              <el-table-column label="参数" min-width="220">
                <template #default="{ row }">
                  {{ row.video_codec || '-' }} · {{ row.width || '-' }}×{{ row.height || '-' }} · {{ fps(row) }}fps
                </template>
              </el-table-column>
              <el-table-column label="运行" width="120">
                <template #default="{ row }">
                  <el-tag :type="runtimeState(row.id) === 'RECORDING' ? 'success' : 'info'">{{ runtimeState(row.id) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </template>

        <template v-else-if="page === 'cameras'">
          <div class="toolbar"><el-button type="primary" @click="dialogVisible = true">添加摄像头</el-button></div>
          <el-card>
            <el-table :data="cameras" empty-text="点击“添加摄像头”开始">
              <el-table-column prop="name" label="名称" min-width="140" />
              <el-table-column prop="ip" label="IP" width="150" />
              <el-table-column prop="rtsp_path" label="RTSP Path" min-width="130" />
              <el-table-column label="视频" min-width="190">
                <template #default="{ row }">{{ row.video_codec || '-' }} {{ row.width || '-' }}×{{ row.height || '-' }} / {{ fps(row) }}fps</template>
              </el-table-column>
              <el-table-column label="音频" width="150">
                <template #default="{ row }">{{ row.audio_codec || '-' }} {{ row.sample_rate ? `${row.sample_rate}Hz` : '' }}</template>
              </el-table-column>
              <el-table-column label="模式" width="120"><template #default="{ row }"><el-tag>{{ row.timestamp_mode }}</el-tag></template></el-table-column>
              <el-table-column label="操作" width="300" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="probe(row)">Probe</el-button>
                  <el-button v-if="runtimeState(row.id) !== 'RECORDING'" size="small" type="success" @click="start(row)">开始</el-button>
                  <el-button v-else size="small" type="warning" @click="stop(row)">停止</el-button>
                  <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </template>

        <template v-else>
          <el-card>
            <el-table :data="recordings" empty-text="暂无已完成录像">
              <el-table-column prop="camera_id" label="Camera ID" width="100" />
              <el-table-column prop="started_at" label="开始时间" min-width="190" />
              <el-table-column label="时长" width="100"><template #default="{ row }">{{ row.duration ? `${row.duration.toFixed(1)}s` : '-' }}</template></el-table-column>
              <el-table-column label="大小" width="110"><template #default="{ row }">{{ sizeText(row.file_size) }}</template></el-table-column>
              <el-table-column label="健康" width="110"><template #default="{ row }"><el-tag :type="row.health_status === 'healthy' ? 'success' : 'warning'">{{ row.health_status }}</el-tag></template></el-table-column>
              <el-table-column prop="upload_status" label="上传" width="100" />
              <el-table-column prop="mp4_path" label="文件" min-width="320" show-overflow-tooltip />
            </el-table>
          </el-card>
        </template>
      </el-main>
    </el-container>
  </el-container>

  <el-dialog v-model="dialogVisible" title="添加 RTSP 摄像头" width="520px">
    <el-form label-width="110px">
      <el-form-item label="名称"><el-input v-model="form.name" placeholder="监控-大厅" /></el-form-item>
      <el-form-item label="IP"><el-input v-model="form.ip" placeholder="192.168.1.100" /></el-form-item>
      <el-form-item label="RTSP端口"><el-input-number v-model="form.rtsp_port" :min="1" :max="65535" /></el-form-item>
      <el-form-item label="用户名"><el-input v-model="form.username" /></el-form-item>
      <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password /></el-form-item>
      <el-form-item label="RTSP路径"><el-input v-model="form.rtsp_path" placeholder="/ch1/main" /></el-form-item>
      <el-form-item label="时间戳模式">
        <el-select v-model="form.timestamp_mode" style="width: 100%">
          <el-option label="Reconstruct（推荐）" value="reconstruct" />
          <el-option label="Native" value="native" />
          <el-option label="Wallclock" value="wallclock" />
        </el-select>
      </el-form-item>
      <el-form-item label="自动录像"><el-switch v-model="form.auto_record" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="createCamera">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
:global(body) { margin: 0; background: #f5f7fa; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.app-shell { min-height: 100vh; }
.sidebar { background: #fff; border-right: 1px solid #ebeef5; }
.brand { height: 60px; display: flex; align-items: center; padding: 0 20px; font-weight: 700; border-bottom: 1px solid #ebeef5; }
.header { height: 60px; background: #fff; border-bottom: 1px solid #ebeef5; display: flex; align-items: center; justify-content: space-between; }
.subtitle { color: #909399; font-size: 12px; margin-left: 12px; }
.header-actions { display: flex; gap: 8px; }
.metric { font-size: 30px; font-weight: 700; }
.muted { color: #909399; font-size: 13px; }
.top-gap { margin-top: 10px; }
.section-card { margin-top: 16px; }
.toolbar { display: flex; justify-content: flex-end; margin-bottom: 12px; }
</style>
