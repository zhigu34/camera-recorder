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
  sub_rtsp_path?: string | null
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

  text.split(/\r?\n/).forEach((rawLine, index) => {
    const lineNumber = index + 1
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) return

    const parts = rawLine.split('|')
    if (parts.length < 4 || parts.length > 8) {
      errors.push(`第 ${lineNumber} 行：字段数量应为 4～8 个，使用 | 分隔`)
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
    const subRtspPath = (parts[7] || '').trim() || null

    if (!name) errors.push(`第 ${lineNumber} 行：名称不能为空`)
    if (!ip) errors.push(`第 ${lineNumber} 行：IP/主机不能为空`)
    if (!password) errors.push(`第 ${lineNumber} 行：密码不能为空`)
    if (!allowedModes.has(rawMode)) errors.push(`第 ${lineNumber} 行：时间戳模式必须是 native / reconstruct / wallclock`)
    if (!Number.isInteger(rtspPort) || rtspPort < 1 || rtspPort > 65535) errors.push(`第 ${lineNumber} 行：RTSP 端口无效`)
    if (name && seenNames.has(name)) errors.push(`第 ${lineNumber} 行：名称“${name}”在本次批量数据中重复`)
    if (name) seenNames.add(name)

    if (name && ip && password && allowedModes.has(rawMode) && Number.isInteger(rtspPort) && rtspPort >= 1 && rtspPort <= 65535) {
      cameras.push({
        name,
        ip,
        rtsp_port: rtspPort,
        username,
        password,
        rtsp_path: rtspPath,
        sub_rtsp_path: subRtspPath,
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
    '# 名称|IP|用户名|密码|主码流RTSP路径|时间戳模式|RTSP端口(可选)|子码流RTSP路径(可选)',
    '监控-大厅|192.168.1.100|admin|你的密码|/ch1/main|reconstruct|554|/ch1/sub',
    '监控-门口|192.168.1.101|admin|你的密码|/ch1/main|native|554|/ch1/sub',
  ].join('\n')
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
  <section class="batch-page">
    <div class="batch-panel">
      <el-alert type="info" :closable="false" show-icon>
        <template #title>格式：名称 | IP | 用户名 | 密码 | 主码流路径 | 时间戳模式 | RTSP端口 | 子码流路径</template>
        最少填写前 4 项。主码流默认 /ch1/main，模式默认 reconstruct，端口默认 554；子码流可以留空。空行和以 # 开头的注释行会自动忽略。
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
        placeholder="监控-大厅|192.168.1.100|admin|你的密码|/ch1/main|reconstruct|554|/ch1/sub"
      />

      <div class="summary">
        <el-tag type="success">可导入 {{ validCount }} 个</el-tag>
        <el-tag v-if="errorCount" type="danger">格式错误 {{ errorCount }} 条</el-tag>
        <span class="security-hint">密码不会回显，后端使用系统密钥加密保存。</span>
      </div>

      <el-alert v-if="parsed.errors.length" class="error-box" title="请修正以下问题" type="error" :closable="false" show-icon>
        <div v-for="item in parsed.errors.slice(0, 20)" :key="item" class="error-line">{{ item }}</div>
        <div v-if="parsed.errors.length > 20" class="error-line">还有 {{ parsed.errors.length - 20 }} 条错误未显示</div>
      </el-alert>

      <el-alert v-if="lastResult" class="result-box" title="导入完成" type="success" :closable="false" show-icon>
        已创建 {{ lastResult.created }} 个，跳过 {{ lastResult.skipped }} 个。
        <span v-if="lastResult.skipped_names.length">跳过：{{ lastResult.skipped_names.join('、') }}</span>
      </el-alert>

      <div class="actions">
        <el-button @click="rawText = ''; lastResult = null">清空</el-button>
        <el-button type="primary" :loading="saving" :disabled="!validCount || errorCount > 0" @click="submitBatch">
          批量添加 {{ validCount ? `(${validCount})` : '' }}
        </el-button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.batch-page{max-width:1120px;margin:0 auto;padding:22px;color:var(--nvr-text)}.batch-panel{padding:18px;border:1px solid var(--nvr-border);border-radius:10px;background:var(--nvr-surface)}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:18px 0 12px}.summary{display:flex;align-items:center;gap:10px;margin-top:12px}.security-hint{margin-left:auto;color:var(--nvr-muted);font-size:11px}.error-box,.result-box{margin-top:16px}.error-line{line-height:1.7}.actions{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}@media(max-width:760px){.batch-page{padding:14px}.toolbar,.summary{align-items:flex-start;flex-direction:column}.security-hint{margin-left:0}}
</style>
