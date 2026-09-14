<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { TopRight } from '@element-plus/icons-vue'

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
  openlist_management_port: number
}

const loading = ref(false)
const saving = ref(false)
const openListManagementPort = ref(5244)
const savedSnapshot = ref('')
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

const segmentDurationPresets = [
  { label: '30 秒', value: 30 },
  { label: '1 分钟', value: 60 },
  { label: '2 分钟', value: 120 },
  { label: '3 分钟', value: 180 },
  { label: '5 分钟', value: 300 },
  { label: '10 分钟', value: 600 },
  { label: '15 分钟', value: 900 },
  { label: '30 分钟', value: 1800 },
  { label: '60 分钟', value: 3600 },
]

function segmentDurationText(seconds: number) {
  if (seconds < 60) return `${seconds} 秒`
  if (seconds % 60 === 0) return `${seconds / 60} 分钟`
  return `${seconds} 秒`
}

function currentSettingsSnapshot() {
  return JSON.stringify({
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
    webdav_password: form.webdav_password,
    clear_webdav_password: form.clear_webdav_password,
    local_retention_hours: form.local_retention_hours,
  })
}

const settingsDirty = computed(() => Boolean(savedSnapshot.value) && currentSettingsSnapshot() !== savedSnapshot.value)
const segmentDurationOptions = computed(() => {
  if (segmentDurationPresets.some((option) => option.value === form.segment_duration_seconds)) {
    return segmentDurationPresets
  }
  return [
    ...segmentDurationPresets,
    { label: `当前自定义值 · ${segmentDurationText(form.segment_duration_seconds)}`, value: form.segment_duration_seconds },
  ].sort((a, b) => a.value - b.value)
})
const retentionLabel = computed(() => form.local_retention_hours < 0 ? '永久保留' : `${form.local_retention_hours} 小时`)
const rtspTimeoutSeconds = computed(() => `${(form.rtsp_timeout_us / 1_000_000).toFixed(1)} 秒`)
const openListManagementUrl = computed(() => {
  const raw = form.webdav_url.trim()
  try {
    const target = new URL(raw || 'http://openlist:5244/dav')
    const internalHosts = new Set(['openlist', 'localhost', '127.0.0.1', '::1'])
    if (internalHosts.has(target.hostname.toLowerCase())) {
      target.hostname = window.location.hostname
      target.port = String(openListManagementPort.value || 5244)
    }
    target.pathname = '/'
    target.search = ''
    target.hash = ''
    target.username = ''
    target.password = ''
    return target.toString()
  } catch {
    const target = new URL(window.location.origin)
    target.port = String(openListManagementPort.value || 5244)
    target.pathname = '/'
    target.search = ''
    target.hash = ''
    return target.toString()
  }
})

function apply(data: SystemSettings) {
  const { openlist_management_port, ...runtime } = data
  openListManagementPort.value = openlist_management_port || 5244
  Object.assign(form, runtime, {
    webdav_password: '',
    clear_webdav_password: false,
  })
  savedSnapshot.value = currentSettingsSnapshot()
}

function openOpenList() {
  window.open(openListManagementUrl.value, '_blank', 'noopener,noreferrer')
}

function confirmDiscardChanges() {
  if (!settingsDirty.value) return true
  return window.confirm('系统设置还有未保存的修改，确定放弃并离开吗？')
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!settingsDirty.value) return
  event.preventDefault()
  event.returnValue = ''
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

onBeforeRouteLeave(() => confirmDiscardChanges())
onBeforeRouteUpdate(() => confirmDiscardChanges())

onMounted(() => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  void load()
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
})
</script>

<template>
  <section class="settings-workspace" v-loading="loading">
    <div class="settings-intro">
      <div>
        <strong>运行时配置</strong>
        <span>配置写入 SQLite；部署参数和密钥仍由 .env 管理。</span>
      </div>
      <el-button :loading="loading" @click="load">重新加载</el-button>
    </div>

    <div class="settings-status-strip">
      <article>
        <span>自动录像恢复</span>
        <strong :class="form.auto_start_enabled ? 'state-ok' : 'state-muted'">{{ form.auto_start_enabled ? '已启用' : '已关闭' }}</strong>
        <em>服务启动后的录像恢复策略</em>
      </article>
      <article>
        <span>OpenList 归档</span>
        <strong :class="form.upload_enabled ? 'state-ok' : 'state-muted'">{{ form.upload_enabled ? '自动上传' : '已关闭' }}</strong>
        <em>{{ form.webdav_password_set ? '凭据已保存' : '未保存密码' }}</em>
      </article>
      <article>
        <span>本地录像保留</span>
        <strong>{{ retentionLabel }}</strong>
        <em>归档成功后的本地保留策略</em>
      </article>
      <article>
        <span>磁盘保护</span>
        <strong>{{ form.storage_warning_percent }}% / {{ form.storage_critical_percent }}%</strong>
        <em>告警 / 严重告警阈值</em>
      </article>
    </div>

    <el-form label-position="top" class="settings-grid">
      <article class="settings-panel">
        <div class="settings-panel-head">
          <div><strong>基础设置</strong><span>控制系统标识与启动行为</span></div>
          <el-tag size="small" effect="plain">SYSTEM</el-tag>
        </div>
        <div class="settings-fields">
          <el-form-item label="系统名称">
            <el-input v-model="form.app_name" />
          </el-form-item>
          <div class="switch-setting">
            <div><strong>启动时自动恢复录像</strong><span>服务启动后按摄像头配置和录制计划恢复 Recorder。</span></div>
            <el-switch v-model="form.auto_start_enabled" />
          </div>
        </div>
      </article>

      <article class="settings-panel">
        <div class="settings-panel-head">
          <div><strong>录像与媒体处理</strong><span>影响切片、RTSP 和 Remux 工作负载</span></div>
          <el-tag size="small" type="warning" effect="plain">RECORDER</el-tag>
        </div>
        <div class="settings-fields settings-fields-grid">
          <el-form-item label="切片时长">
            <el-select v-model="form.segment_duration_seconds" style="width: 220px" placeholder="选择单段录像时长">
              <el-option
                v-for="option in segmentDurationOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <small>每个录像文件约 {{ segmentDurationText(form.segment_duration_seconds) }}；修改后重启对应摄像头连接生效。</small>
          </el-form-item>
          <el-form-item label="RTSP 超时">
            <div class="number-field">
              <el-input-number v-model="form.rtsp_timeout_us" :min="500000" :max="120000000" :step="500000" />
              <span>微秒</span>
            </div>
            <small>当前约 {{ rtspTimeoutSeconds }}。</small>
          </el-form-item>
          <el-form-item label="Remux 并发数">
            <el-input-number v-model="form.remux_concurrency" :min="1" :max="16" />
            <small>并发越高，录像整理速度越快，但会增加 CPU / I/O 压力。</small>
          </el-form-item>
          <div class="switch-setting compact-switch">
            <div><strong>按整点对齐切片</strong><span>便于按时间检索和跨日连续回放。</span></div>
            <el-switch v-model="form.align_segments_to_clock" />
          </div>
        </div>
      </article>

      <article class="settings-panel">
        <div class="settings-panel-head">
          <div><strong>磁盘保护</strong><span>定义本地录像盘的容量风险边界</span></div>
          <el-tag size="small" type="danger" effect="plain">STORAGE</el-tag>
        </div>
        <div class="storage-thresholds">
          <el-form-item label="告警阈值">
            <div class="number-field">
              <el-input-number v-model="form.storage_warning_percent" :min="1" :max="99" />
              <span>%</span>
            </div>
            <small>达到该占用率后进入 warning。</small>
          </el-form-item>
          <el-form-item label="严重告警阈值">
            <div class="number-field">
              <el-input-number v-model="form.storage_critical_percent" :min="1" :max="100" />
              <span>%</span>
            </div>
            <small>达到该占用率后进入 critical。</small>
          </el-form-item>
        </div>
        <div class="threshold-rail" aria-hidden="true">
          <span class="warning-mark" :style="{ left: `${form.storage_warning_percent}%` }"></span>
          <span class="critical-mark" :style="{ left: `${form.storage_critical_percent}%` }"></span>
        </div>
        <div class="threshold-legend"><span>0%</span><span class="warning-text">告警 {{ form.storage_warning_percent }}%</span><span class="critical-text">严重 {{ form.storage_critical_percent }}%</span><span>100%</span></div>
      </article>

      <article id="archive-settings" class="settings-panel archive-panel">
        <div class="settings-panel-head">
          <div><strong>OpenList / WebDAV 归档</strong><span>统一远端存储入口，不绑定具体网盘品牌</span></div>
          <div class="settings-panel-actions">
            <el-button size="small" plain @click="openOpenList">
              打开 OpenList
              <el-icon class="external-link-icon"><TopRight /></el-icon>
            </el-button>
            <el-tag size="small" type="success" effect="plain">ARCHIVE</el-tag>
          </div>
        </div>

        <div class="archive-banner">
          <div><strong>{{ form.upload_enabled ? '自动归档已启用' : '自动归档当前关闭' }}</strong><span>后端只依赖标准 WebDAV；OpenList 可挂载任意可写存储。</span></div>
          <el-switch v-model="form.upload_enabled" size="large" />
        </div>

        <div class="settings-fields settings-fields-grid archive-grid">
          <el-form-item label="上传并发数">
            <el-input-number v-model="form.upload_concurrency" :min="1" :max="16" />
            <small>控制同时执行的远端上传任务数。</small>
          </el-form-item>
          <el-form-item label="最大重试次数">
            <el-input-number v-model="form.upload_retry_max" :min="1" :max="100" />
            <small>网络或 WebDAV 临时故障时的最大重试次数。</small>
          </el-form-item>
          <el-form-item label="本地保留时间">
            <div class="number-field">
              <el-input-number v-model="form.local_retention_hours" :min="-1" :max="87600" />
              <span>小时</span>
            </div>
            <small>-1 表示永不自动删除本地录像。</small>
          </el-form-item>
          <div class="archive-spacer"></div>
          <el-form-item label="OpenList WebDAV 地址" class="wide-field">
            <el-input v-model="form.webdav_url" placeholder="http://openlist:5244/dav" />
            <small>可填 WebDAV 根地址，也可直接指向某个挂载目录，例如 /dav/archive。</small>
          </el-form-item>
          <el-form-item label="远端归档目录" class="wide-field">
            <el-input v-model="form.webdav_root" placeholder="监控录像" />
            <small>使用 WebDAV 根地址时可写“挂载名/监控录像”；已指向挂载目录时只需写“监控录像”。</small>
          </el-form-item>
          <el-form-item label="WebDAV 用户名">
            <el-input v-model="form.webdav_username" autocomplete="username" />
          </el-form-item>
          <el-form-item label="WebDAV 密码">
            <el-input
              v-model="form.webdav_password"
              type="password"
              show-password
              autocomplete="new-password"
              :placeholder="form.webdav_password_set ? '已加密保存；留空保持不变' : '请输入 WebDAV 密码'"
            />
            <div v-if="form.webdav_password_set" class="password-actions">
              <el-tag type="success" size="small">已加密保存</el-tag>
              <el-checkbox v-model="form.clear_webdav_password">清除已保存密码</el-checkbox>
            </div>
          </el-form-item>
        </div>
      </article>
    </el-form>

    <div class="settings-savebar">
      <div><strong>保存运行时配置</strong><span>{{ settingsDirty ? '存在未保存修改。' : '部分 Recorder 参数需要重启对应摄像头连接后才完全生效。' }}</span></div>
      <div class="settings-save-actions">
        <el-button :disabled="saving" @click="load">放弃修改</el-button>
        <el-button type="primary" :loading="saving" :disabled="!settingsDirty" @click="save">保存设置</el-button>
      </div>
    </div>
  </section>
</template>