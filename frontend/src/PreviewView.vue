<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

type PreviewStream = 'auto' | 'main' | 'sub'

interface Camera {
  id: number
  name: string
  ip: string
  rtsp_port: number
  username: string
  rtsp_path: string
  sub_rtsp_path?: string | null
  status: string
}

const cameras = ref<Camera[]>([])
const loading = ref(false)
const savingPath = ref(false)
const selectedId = ref<number | null>(null)
const streamMode = ref<PreviewStream>('auto')
const previewFps = ref(8)
const previewWidth = ref(960)
const playing = ref(false)
const previewNonce = ref(0)
const previewFailed = ref(false)
const subPathDraft = ref('')

const selectedCamera = computed(() =>
  cameras.value.find((camera) => camera.id === selectedId.value) || null,
)

function inferSubPath(path: string) {
  const index = path.lastIndexOf('/main')
  if (index >= 0) return `${path.slice(0, index)}/sub${path.slice(index + 5)}`
  if (path.endsWith('main')) return `${path.slice(0, -4)}sub`
  return ''
}

const inferredSubPath = computed(() =>
  selectedCamera.value ? inferSubPath(selectedCamera.value.rtsp_path) : '',
)

const effectiveSubPath = computed(() =>
  selectedCamera.value?.sub_rtsp_path || inferredSubPath.value || '',
)

const previewUrl = computed(() => {
  if (!playing.value || !selectedCamera.value) return ''
  const query = new URLSearchParams({
    stream: streamMode.value,
    fps: String(previewFps.value),
    width: String(previewWidth.value),
    v: String(previewNonce.value),
  })
  return `/api/cameras/${selectedCamera.value.id}/preview.mjpeg?${query.toString()}`
})

async function loadCameras() {
  loading.value = true
  try {
    const { data } = await axios.get<Camera[]>('/api/cameras')
    cameras.value = data
    if (selectedId.value === null && data.length) selectedId.value = data[0].id
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '加载摄像头失败')
  } finally {
    loading.value = false
  }
}

function restartPreview() {
  previewFailed.value = false
  previewNonce.value += 1
  playing.value = true
}

function stopPreview() {
  playing.value = false
  previewFailed.value = false
}

function onPreviewError() {
  previewFailed.value = true
}

async function saveSubPath() {
  if (!selectedCamera.value) return
  savingPath.value = true
  try {
    const value = subPathDraft.value.trim()
    await axios.put(`/api/cameras/${selectedCamera.value.id}`, {
      sub_rtsp_path: value || null,
    })
    ElMessage.success(value ? '子码流路径已保存' : '已清除自定义子码流路径，将使用自动推测')
    await loadCameras()
    if (playing.value) restartPreview()
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '保存失败')
  } finally {
    savingPath.value = false
  }
}

function goBack() {
  window.location.href = '/'
}

watch(selectedCamera, (camera) => {
  subPathDraft.value = camera?.sub_rtsp_path || ''
  previewFailed.value = false
  if (playing.value) restartPreview()
})

watch([streamMode, previewFps, previewWidth], () => {
  if (playing.value) restartPreview()
})

onMounted(loadCameras)
</script>

<template>
  <div class="preview-page" v-loading="loading">
    <div class="page-head">
      <div>
        <h2>实时预览</h2>
        <p>浏览器通过 MJPEG 低延迟预览；录像仍使用原始主码流，不会被预览设置影响。</p>
      </div>
      <el-button @click="goBack">返回主界面</el-button>
    </div>

    <div class="layout">
      <el-card class="control-card">
        <el-form label-position="top">
          <el-form-item label="摄像头">
            <el-select v-model="selectedId" style="width: 100%" placeholder="请选择摄像头">
              <el-option
                v-for="camera in cameras"
                :key="camera.id"
                :label="`${camera.name} · ${camera.ip}`"
                :value="camera.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="预览码流">
            <el-radio-group v-model="streamMode">
              <el-radio-button value="auto">自动</el-radio-button>
              <el-radio-button value="sub">子码流</el-radio-button>
              <el-radio-button value="main">主码流</el-radio-button>
            </el-radio-group>
            <div class="hint">自动模式优先子码流，无法确定子码流时才使用主码流。</div>
          </el-form-item>

          <el-form-item label="子码流 RTSP 路径">
            <el-input v-model="subPathDraft" placeholder="例如 /ch1/sub" clearable />
            <div class="hint">
              <template v-if="selectedCamera?.sub_rtsp_path">当前使用已保存路径。</template>
              <template v-else-if="inferredSubPath">未保存时会自动尝试 {{ inferredSubPath }}。</template>
              <template v-else>当前主码流路径无法自动推测，请手工填写。</template>
            </div>
            <el-button class="path-save" :loading="savingPath" @click="saveSubPath">保存子码流路径</el-button>
          </el-form-item>

          <el-form-item label="预览帧率">
            <el-slider v-model="previewFps" :min="2" :max="15" :step="1" show-input />
          </el-form-item>

          <el-form-item label="最大预览宽度">
            <el-select v-model="previewWidth" style="width: 100%">
              <el-option label="640（省资源）" :value="640" />
              <el-option label="960（推荐）" :value="960" />
              <el-option label="1280" :value="1280" />
              <el-option label="1920" :value="1920" />
            </el-select>
          </el-form-item>

          <el-alert
            v-if="streamMode === 'main'"
            type="warning"
            :closable="false"
            show-icon
            title="主码流分辨率较高，实时转 MJPEG 会明显增加服务器 CPU 使用率。"
          />

          <div class="actions">
            <el-button v-if="!playing" type="primary" :disabled="!selectedCamera" @click="restartPreview">开始预览</el-button>
            <template v-else>
              <el-button type="primary" plain @click="restartPreview">重新连接</el-button>
              <el-button type="danger" plain @click="stopPreview">停止预览</el-button>
            </template>
          </div>
        </el-form>
      </el-card>

      <el-card class="viewer-card">
        <template #header>
          <div class="viewer-head">
            <strong>{{ selectedCamera?.name || '未选择摄像头' }}</strong>
            <div class="viewer-tags">
              <el-tag v-if="selectedCamera" size="small">{{ selectedCamera.ip }}</el-tag>
              <el-tag v-if="playing" size="small" type="success">LIVE</el-tag>
            </div>
          </div>
        </template>

        <div class="viewer">
          <img
            v-if="previewUrl"
            :key="previewUrl"
            :src="previewUrl"
            :alt="selectedCamera?.name || '实时预览'"
            @error="onPreviewError"
          />
          <div v-else class="placeholder">选择摄像头后点击“开始预览”</div>
          <div v-if="previewFailed" class="preview-error">
            预览连接失败。请检查子码流路径、摄像头账号、网络连通性；也可以切换到主码流验证。
          </div>
        </div>

        <div v-if="selectedCamera" class="stream-info">
          <span>主码流：{{ selectedCamera.rtsp_path }}</span>
          <span>子码流：{{ effectiveSubPath || '未配置' }}</span>
        </div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
:global(body) {
  margin: 0;
  background: #f5f7fa;
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.preview-page { max-width: 1380px; margin: 0 auto; padding: 28px 24px 60px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; margin-bottom: 18px; }
h2 { margin: 0 0 8px; }
p { margin: 0; color: #909399; }
.layout { display: grid; grid-template-columns: 330px minmax(0, 1fr); gap: 18px; align-items: start; }
.control-card { position: sticky; top: 18px; }
.hint { color: #909399; font-size: 12px; line-height: 1.5; margin-top: 7px; width: 100%; }
.path-save { margin-top: 10px; }
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
.viewer-head { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
.viewer-tags { display: flex; gap: 8px; }
.viewer { min-height: 520px; background: #111; display: flex; align-items: center; justify-content: center; position: relative; overflow: hidden; border-radius: 6px; }
.viewer img { display: block; width: 100%; height: 100%; max-height: 72vh; object-fit: contain; }
.placeholder { color: #8c8c8c; font-size: 14px; }
.preview-error { position: absolute; left: 20px; right: 20px; bottom: 20px; padding: 12px 14px; border-radius: 6px; color: #fff; background: rgba(180, 35, 35, 0.88); font-size: 13px; line-height: 1.5; }
.stream-info { display: flex; flex-wrap: wrap; gap: 12px 24px; margin-top: 12px; color: #909399; font-size: 12px; }
@media (max-width: 900px) {
  .layout { grid-template-columns: 1fr; }
  .control-card { position: static; }
  .viewer { min-height: 320px; }
}
</style>
