<script setup lang="ts">
import { onMounted, ref } from 'vue'
import axios from 'axios'

interface SystemStatus {
  app: string
  segment_duration_seconds: number
  ffmpeg: {
    ffmpeg_available: boolean
    ffprobe_available: boolean
    setts_available: boolean
    ffmpeg_version?: string | null
    ffprobe_version?: string | null
  }
}

const loading = ref(true)
const error = ref('')
const status = ref<SystemStatus | null>(null)

async function loadStatus() {
  loading.value = true
  error.value = ''

  try {
    const response = await axios.get<SystemStatus>('/api/system/status')
    status.value = response.data
  } catch (err) {
    error.value = err instanceof Error ? err.message : '无法连接后端'
  } finally {
    loading.value = false
  }
}

onMounted(loadStatus)
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="220px" class="sidebar">
      <div class="brand">Camera Recorder</div>
      <el-menu default-active="dashboard">
        <el-menu-item index="dashboard">仪表盘</el-menu-item>
        <el-menu-item index="cameras">摄像头</el-menu-item>
        <el-menu-item index="recordings">录像文件</el-menu-item>
        <el-menu-item index="uploads">上传任务</el-menu-item>
        <el-menu-item index="events">事件中心</el-menu-item>
        <el-menu-item index="settings">设置</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <strong>系统状态</strong>
        <el-button size="small" @click="loadStatus">刷新</el-button>
      </el-header>

      <el-main>
        <el-alert v-if="error" :title="error" type="error" show-icon />

        <el-skeleton v-if="loading" :rows="5" animated />

        <template v-else-if="status">
          <el-row :gutter="16">
            <el-col :span="8">
              <el-card>
                <template #header>FFmpeg</template>
                <el-tag :type="status.ffmpeg.ffmpeg_available ? 'success' : 'danger'">
                  {{ status.ffmpeg.ffmpeg_available ? '可用' : '不可用' }}
                </el-tag>
                <p class="muted">{{ status.ffmpeg.ffmpeg_version || '-' }}</p>
              </el-card>
            </el-col>

            <el-col :span="8">
              <el-card>
                <template #header>ffprobe</template>
                <el-tag :type="status.ffmpeg.ffprobe_available ? 'success' : 'danger'">
                  {{ status.ffmpeg.ffprobe_available ? '可用' : '不可用' }}
                </el-tag>
                <p class="muted">{{ status.ffmpeg.ffprobe_version || '-' }}</p>
              </el-card>
            </el-col>

            <el-col :span="8">
              <el-card>
                <template #header>setts / prescale</template>
                <el-tag :type="status.ffmpeg.setts_available ? 'success' : 'danger'">
                  {{ status.ffmpeg.setts_available ? '支持' : '不支持' }}
                </el-tag>
                <p class="muted">默认切片 {{ status.segment_duration_seconds }} 秒</p>
              </el-card>
            </el-col>
          </el-row>

          <el-card class="next-card">
            <template #header>V0.1 下一步</template>
            <p>摄像头 CRUD → 单会话 RTSP Probe → FFmpegCommandBuilder → CameraWorker → 10 分钟切片 → Remux → 健康检查。</p>
          </el-card>
        </template>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
:global(body) {
  margin: 0;
  background: #f5f7fa;
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.app-shell {
  min-height: 100vh;
}

.sidebar {
  background: #fff;
  border-right: 1px solid #ebeef5;
}

.brand {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  font-weight: 700;
  border-bottom: 1px solid #ebeef5;
}

.header {
  background: #fff;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.muted {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.next-card {
  margin-top: 16px;
}
</style>
