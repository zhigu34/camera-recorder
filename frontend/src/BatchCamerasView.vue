<script setup lang="ts">
import { computed, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

type TimestampMode = 'native' | 'reconstruct' | 'wallclock'

interface CameraCreatePayload {
  name: string
  ip: string
  rtsp_port: number
  username: string
  password: string
  rtsp_path: string
  enabled: boolean
  auto_record: boolean
  timestamp_mode: TimestampMode
}

interface BatchResult {
  created: number
  skipped: number
  created_ids: number[]
  skipped_names: string[]
}

interface ParsedBatch {
  cameras: CameraCreatePayload[]
  errors: string[]
}

const rawText = ref('')
const skipExisting = ref(true)
const saving = ref(false)
const lastResult = ref<BatchResult | null>(null)

const allowedModes = new Set<TimestampMode>(['native', 'reconstruct', 'wallclock'])

function parseBatch(text: string): ParsedBatch {
  const cameras: CameraCreatePayload[] = []
  const errors: string[] = []
  const seenNames = new Set<string>()

  const lines = text.split(/\r?\n/)
  lines.forEach((rawLine, index) => {
    const lineNumber = index + 1
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) return

    const parts = rawLine.split('|')
    if (parts.length < 4 || parts.length > 7) {
      errors.push(`第 ${lineNumber} 行：字段数量应为 4～7 个，使用 | 分隔`)
      return
    }

    const name = (parts[0] || '').trim()
    const ip = (parts[1] || '').trim()
    const username = (parts[2] || '').trim() || 'admin'
    const password = parts[3] ?? ''
    const rtspPath = (parts[4] || '').trim() || '/ch1/main'
    const rawMode = ((parts[5] || '').trim() || 'reconstruct') as TimestampMode
    const rawPort = (parts[6] || '').trim()
    const rtspPort = rawPort ? Number(rawPort) : 554

    if (!name) errors.push(`第 ${lineNumber} 行：名称不能为空`)
    if (!ip) errors.push(`第 ${lineNumber} 行：IP/主机不能为空`)
    if (!password) errors.push(`第 ${lineNumber} 行：密码不能为空`)
    if (!allowedModes.has(rawMode)) {
      errors.push(`第 ${lineNumber} 行：时间戳模式必须是 native / reconstruct / wallclock`)
    }
    if (!Number.isInteger(rtspPort) || rtspPort < 1 || rtspPort > 65535) {
      errors.push(`第 ${lineNumber} 行：RTSP 端口无效`)
    }
    if (name && seenNames.has(name)) {
      errors.push(`第 ${lineNumber} 行：名称“${name}”在本次批量数据中重复`)
    }
    if (name) seenNames.add(name)

    if (
      name &&
      ip &&
      password &&
      allowedModes.has(rawMode) &&
      Number.isInteger(rtspPort) &&
      rtspPort >= 1 &&
      rtspPort <= 65535
    ) {
      cameras.push({
        name,
        ip,
        rtsp_port: rtspPort,
        username,
        password,
        rtsp_path: rtspPath,
        timestamp_mode: rawMode,
        enabled: true,
        auto_record: false,
      })
    }
  })

  return { cameras, errors }
}

const parsed = computed(() => parseBatch(rawText.value))
const validCount = computed(() => parsed.value.cameras.length)
const errorCount = computed(() => parsed.value.errors.length)

function fillExample() {
  rawText.value = [
    '# 名称|IP|用户名|密码|RTSP路径|时间戳模式|RTSP端口(可选)',
    '监控-大厅|192.168.1.100|admin|你的密码|/ch1/main|reconstruct',
    '监控-门口|192.168.1.101|admin|你的密码|/ch1/main|native|554',
  ].join('\n')
}

function goBack() {
  window.location.href = '/'
}

async function submitBatch() {
  lastResult.value = null
  if (!rawText.value.trim()) {
    ElMessage.warning('请先粘贴摄像头数据')
    return
  }
  if (parsed.value.errors.length) {
    ElMessage.error(`存在 ${parsed.value.errors.length} 条格式错误，请先修正`)
    return
  }
  if (!parsed.value.cameras.length) {
    ElMessage.warning('没有可导入的摄像头')
    return
  }

  saving.value = true
  try {
    const { data } = await axios.post<BatchResult>('/api/cameras/batch', {
      cameras: parsed.value.cameras,
      skip_existing: skipExisting.value,
    })
    lastResult.value = data
    const skippedText = data.skipped ? `，跳过 ${data.skipped} 个已存在项` : ''
    ElMessage.success(`成功添加 ${data.created} 个摄像头${skippedText}`)
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '批量添加失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="batch-page">
    <div class="page-head">
      <div>
        <h2>批量添加摄像头</h2>
        <p>一行一个摄像头，使用竖线 <code>|</code> 分隔字段。</p>
      </div>
      <el-button @click="goBack">返回主界面</el-button>
    </div>

    <el-card>
      <el-alert type="info" :closable="false" show-icon>
        <template #title>格式：名称 | IP | 用户名 | 密码 | RTSP路径 | 时间戳模式 | RTSP端口（可选）</template>
        用户名留空默认 admin，RTSP 路径留空默认 /ch1/main，时间戳模式留空默认 reconstruct，端口留空默认 554。
        空行和以 # 开头的注释行会自动忽略。
      </el-alert>

      <div class="toolbar">
        <el-button size="small" @click="fillExample">填入示例</el-button>
        <el-switch v-model="skipExisting" active-text="跳过已存在的同名摄像头" />
      </div>

      <el-input
        v-model="rawText"
        type="textarea"
        :rows="14"
        resize="vertical"
        spellcheck="false"
        placeholder="监控-大厅|192.168.1.100|admin|你的密码|/ch1/main|reconstruct"
      />

      <div class="summary">
        <el-tag type="success">可导入 {{ validCount }} 个</el-tag>
        <el-tag v-if="errorCount" type="danger">格式错误 {{ errorCount }} 条</el-tag>
        <span class="security-hint">密码不会回显到摄像头列表，后端会加密保存。</span>
      </div>

      <el-alert
        v-if="parsed.errors.length"
        class="error-box"
        title="请修正以下问题"
        type="error"
        :closable="false"
        show-icon
      >
        <div v-for="item in parsed.errors.slice(0, 20)" :key="item" class="error-line">{{ item }}</div>
        <div v-if="parsed.errors.length > 20" class="error-line">还有 {{ parsed.errors.length - 20 }} 条错误未显示</div>
      </el-alert>

      <el-alert
        v-if="lastResult"
        class="result-box"
        title="导入完成"
        type="success"
        :closable="false"
        show-icon
      >
        已创建 {{ lastResult.created }} 个，跳过 {{ lastResult.skipped }} 个。
        <span v-if="lastResult.skipped_names.length">跳过：{{ lastResult.skipped_names.join('、') }}</span>
      </el-alert>

      <div class="actions">
        <el-button @click="rawText = ''; lastResult = null">清空</el-button>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!validCount || errorCount > 0"
          @click="submitBatch"
        >
          批量添加 {{ validCount ? `(${validCount})` : '' }}
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
:global(body) {
  margin: 0;
  background: #f5f7fa;
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.batch-page { max-width: 1080px; margin: 0 auto; padding: 28px 24px 60px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
h2 { margin: 0 0 8px; }
p { margin: 0; color: #909399; }
code { background: #f2f3f5; border-radius: 4px; padding: 1px 5px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 18px 0 12px; }
.summary { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
.security-hint { color: #909399; font-size: 12px; margin-left: auto; }
.error-box, .result-box { margin-top: 16px; }
.error-line { line-height: 1.7; }
.actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
</style>
