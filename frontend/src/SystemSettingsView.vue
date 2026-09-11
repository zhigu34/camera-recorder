<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

interface SystemSettings {
  app_name: string
  segment_duration_seconds: number
  remux_concurrency: number
  rtsp_timeout_us: number
  auto_start_enabled: boolean
  align_segments_to_clock: boolean
  storage_warning_percent: number
  storage_critical_percent: number
  upload_enabled: boolean
  upload_concurrency: number
  upload_retry_max: number
  webdav_url: string
  webdav_root: string
  webdav_username: string
  webdav_password_set: boolean
  local_retention_hours: number
}

const loading = ref(false)
const saving = ref(false)
const form = reactive({
  app_name: 'Camera Recorder',
  segment_duration_seconds: 600,
  remux_concurrency: 2,
  rtsp_timeout_us: 5_000_000,
  auto_start_enabled: true,
  align_segments_to_clock: true,
  storage_warning_percent: 80,
  storage_critical_percent: 90,
  upload_enabled: false,
  upload_concurrency: 2,
  upload_retry_max: 8,
  webdav_url: 'http://openlist:5244/dav',
  webdav_root: '监控录像',
  webdav_username: 'admin',
  webdav_password: '',
  webdav_password_set: false,
  clear_webdav_password: false,
  local_retention_hours: 48,
})

function apply(data: SystemSettings) {
  Object.assign(form, data, {
    webdav_password: '',
    clear_webdav_password: false,
  })
}

async function load() {
  loading.value = true
  try {
    const { data } = await axios.get<SystemSettings>('/api/settings')
    apply(data)
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '加载设置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload = {
      app_name: form.app_name,
      segment_duration_seconds: form.segment_duration_seconds,
      remux_concurrency: form.remux_concurrency,
      rtsp_timeout_us: form.rtsp_timeout_us,
      auto_start_enabled: form.auto_start_enabled,
      align_segments_to_clock: form.align_segments_to_clock,
      storage_warning_percent: form.storage_warning_percent,
      storage_critical_percent: form.storage_critical_percent,
      upload_enabled: form.upload_enabled,
      upload_concurrency: form.upload_concurrency,
      upload_retry_max: form.upload_retry_max,
      webdav_url: form.webdav_url,
      webdav_root: form.webdav_root,
      webdav_username: form.webdav_username,
      webdav_password: form.webdav_password || null,
      clear_webdav_password: form.clear_webdav_password,
      local_retention_hours: form.local_retention_hours,
    }
    const { data } = await axios.put<SystemSettings>('/api/settings', payload)
    apply(data)
    ElMessage.success('系统设置已保存到 SQLite')
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

function back() {
  window.location.href = '/'
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="topbar">
      <div>
        <h2>系统设置</h2>
        <div class="hint">运行时配置保存到 SQLite；.env 只保留部署参数和密钥。</div>
      </div>
      <el-button @click="back">返回主界面</el-button>
    </div>

    <el-card>
      <el-form label-width="190px" class="settings-form">
        <el-divider content-position="left">基础</el-divider>
        <el-form-item label="系统名称"><el-input v-model="form.app_name" /></el-form-item>
        <el-form-item label="启动时自动恢复录像"><el-switch v-model="form.auto_start_enabled" /></el-form-item>

        <el-divider content-position="left">录像</el-divider>
        <el-form-item label="切片时长">
          <el-input-number v-model="form.segment_duration_seconds" :min="30" :max="86400" :step="60" />
          <span class="unit">秒</span>
          <span class="hint">修改后重启对应摄像头连接生效</span>
        </el-form-item>
        <el-form-item label="按整点对齐切片"><el-switch v-model="form.align_segments_to_clock" /></el-form-item>
        <el-form-item label="RTSP 超时">
          <el-input-number v-model="form.rtsp_timeout_us" :min="500000" :max="120000000" :step="500000" />
          <span class="unit">微秒</span>
        </el-form-item>
        <el-form-item label="Remux 并发数"><el-input-number v-model="form.remux_concurrency" :min="1" :max="16" /></el-form-item>

        <el-divider content-position="left">磁盘</el-divider>
        <el-form-item label="磁盘告警阈值">
          <el-input-number v-model="form.storage_warning_percent" :min="1" :max="99" />
          <span class="unit">%</span>
        </el-form-item>
        <el-form-item label="磁盘严重告警阈值">
          <el-input-number v-model="form.storage_critical_percent" :min="1" :max="100" />
          <span class="unit">%</span>
        </el-form-item>

        <el-divider content-position="left">OpenList / 网盘归档</el-divider>
        <el-alert class="upload-hint" type="info" :closable="false" show-icon>
          OpenList 作为统一 WebDAV 入口，后端可以挂载任意 OpenList 支持的网盘或对象存储；这里不绑定具体网盘品牌。
        </el-alert>
        <el-form-item label="自动上传"><el-switch v-model="form.upload_enabled" /></el-form-item>
        <el-form-item label="上传并发数"><el-input-number v-model="form.upload_concurrency" :min="1" :max="16" /></el-form-item>
        <el-form-item label="最大重试次数"><el-input-number v-model="form.upload_retry_max" :min="1" :max="100" /></el-form-item>
        <el-form-item label="本地保留时间">
          <el-input-number v-model="form.local_retention_hours" :min="-1" :max="87600" />
          <span class="unit">小时</span>
          <span class="hint">-1 表示永不自动删除</span>
        </el-form-item>
        <el-form-item label="OpenList WebDAV 地址">
          <el-input v-model="form.webdav_url" placeholder="http://openlist:5244/dav" />
          <span class="hint block-hint">可填 OpenList WebDAV 根地址，也可直接指向某个挂载目录，例如 /dav/aliyun。</span>
        </el-form-item>
        <el-form-item label="远端归档目录">
          <el-input v-model="form.webdav_root" placeholder="监控录像" />
          <span class="hint block-hint">使用 WebDAV 根地址时，可写成“网盘挂载名/监控录像”；直接指向挂载目录时只需写“监控录像”。</span>
        </el-form-item>
        <el-form-item label="WebDAV 用户名"><el-input v-model="form.webdav_username" /></el-form-item>
        <el-form-item label="WebDAV 密码">
          <el-input
            v-model="form.webdav_password"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="form.webdav_password_set ? '已加密保存；留空保持不变' : '请输入 WebDAV 密码'"
          />
          <div class="password-actions" v-if="form.webdav_password_set">
            <el-tag type="success" size="small">已加密保存</el-tag>
            <el-checkbox v-model="form.clear_webdav_password">清除已保存密码</el-checkbox>
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
          <el-button @click="load">重新加载</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
:global(body) { margin: 0; background: #f5f7fa; font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.page { max-width: 980px; margin: 0 auto; padding: 28px; }
.topbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
h2 { margin: 0 0 6px; }
.settings-form { max-width: 820px; }
.hint { color: #909399; font-size: 12px; margin-left: 12px; }
.topbar .hint { margin-left: 0; }
.block-hint { display: block; width: 100%; margin: 7px 0 0; line-height: 1.6; }
.upload-hint { margin-bottom: 18px; }
.unit { margin-left: 8px; color: #606266; }
.password-actions { width: 100%; display: flex; gap: 14px; align-items: center; margin-top: 8px; }
</style>
