<script setup lang="ts">
import { computed, ref } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { CircleCheckFilled, DocumentCopy, WarningFilled } from '@element-plus/icons-vue'

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

const emit = defineEmits<{
  (event: 'completed'): void
  (event: 'close'): void
}>()

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
const canSubmit = computed(() => validCount.value > 0 && errorCount.value === 0 && !saving.value)

function fillExample() {
  rawText.value = [
    '# 名称|IP|用户名|密码|主码流路径|时间戳模式|RTSP端口|子码流路径',
    '监控-大厅|192.168.1.100|admin|你的密码|/ch1/main|reconstruct|554|/ch1/sub',
    '监控-门口|192.168.1.101|admin|你的密码|/ch1/main|native|554|/ch1/sub',
  ].join('\n')
  lastResult.value = null
}

function clearAll() {
  rawText.value = ''
  lastResult.value = null
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
    emit('completed')
  } catch (error) {
    ElMessage.error(axios.isAxiosError(error) ? error.response?.data?.detail || error.message : '批量添加失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="batch-importer">
    <div class="import-hero">
      <div class="hero-icon"><DocumentCopy /></div>
      <div>
        <strong>一次粘贴，多路导入</strong>
        <span>每行一台摄像头。系统会先在浏览器内校验格式，确认无误后再提交。</span>
      </div>
      <el-switch v-model="skipExisting" inline-prompt active-text="跳过重名" inactive-text="严格导入" />
    </div>

    <div class="import-layout">
      <aside class="import-guide">
        <div class="guide-title">字段说明</div>
        <ol>
          <li><b>必填</b><span>名称 · IP/主机 · 用户名 · 密码</span></li>
          <li><b>可选</b><span>主码流 · 时间戳模式 · 端口 · 子码流</span></li>
          <li><b>默认</b><span>/ch1/main · reconstruct · 554</span></li>
        </ol>
        <div class="format-box">
          <code>名称 | IP | 用户名 | 密码 | 主码流 | 模式 | 端口 | 子码流</code>
        </div>
        <button class="example-button" type="button" @click="fillExample">填入示例数据</button>
        <p>空行与以 <code>#</code> 开头的注释行会忽略。密码仅提交给后端并加密保存，不会在导入结果中回显。</p>
      </aside>

      <div class="import-editor">
        <div class="editor-head">
          <div><strong>摄像头数据</strong><span>支持直接从表格或文本编辑器整理后粘贴</span></div>
          <div class="parse-state">
            <span class="valid"><CircleCheckFilled />{{ validCount }} 可导入</span>
            <span v-if="errorCount" class="invalid"><WarningFilled />{{ errorCount }} 错误</span>
          </div>
        </div>

        <el-input
          v-model="rawText"
          class="batch-textarea"
          type="textarea"
          :rows="13"
          resize="vertical"
          spellcheck="false"
          placeholder="监控-大厅|192.168.1.100|admin|密码|/ch1/main|reconstruct|554|/ch1/sub"
          @input="lastResult = null"
        />

        <div v-if="parsed.errors.length" class="validation-panel danger">
          <div class="validation-title"><WarningFilled /><strong>请先修正格式问题</strong></div>
          <div class="validation-list">
            <span v-for="item in parsed.errors.slice(0, 12)" :key="item">{{ item }}</span>
            <span v-if="parsed.errors.length > 12">还有 {{ parsed.errors.length - 12 }} 条未显示</span>
          </div>
        </div>

        <div v-if="lastResult" class="validation-panel success">
          <div class="validation-title"><CircleCheckFilled /><strong>导入完成</strong></div>
          <div class="result-line">
            <span>已创建 <b>{{ lastResult.created }}</b> 台</span>
            <span>跳过 <b>{{ lastResult.skipped }}</b> 台</span>
            <span v-if="lastResult.skipped_names.length" class="skipped">{{ lastResult.skipped_names.join('、') }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="import-footer">
      <div class="footer-note">新增摄像头默认启用，但不会自动录像；可在摄像头或录制计划中再开启。</div>
      <div class="footer-actions">
        <el-button @click="clearAll">清空</el-button>
        <el-button @click="emit('close')">关闭</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="submitBatch">
          批量添加{{ validCount ? ` ${validCount} 台` : '' }}
        </el-button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.batch-importer{color:var(--nvr-text);background:var(--nvr-bg)}
.import-hero{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid var(--nvr-border);background:linear-gradient(90deg,rgba(76,141,255,.07),transparent 58%),#0f151c}.hero-icon{width:34px;height:34px;display:grid;place-items:center;border:1px solid rgba(76,141,255,.2);border-radius:9px;color:var(--nvr-blue);background:rgba(76,141,255,.08)}.hero-icon :deep(svg){width:17px}.import-hero>div:nth-child(2){display:flex;min-width:0;flex-direction:column;gap:4px}.import-hero strong{font-size:12px}.import-hero span{color:var(--nvr-muted);font-size:10px;line-height:1.5}
.import-layout{display:grid;grid-template-columns:250px minmax(0,1fr);min-height:430px}.import-guide{padding:18px;border-right:1px solid var(--nvr-border);background:#10161e}.guide-title{margin-bottom:12px;color:#aeb9c6;font-size:10px;font-weight:700;letter-spacing:.08em}.import-guide ol{display:flex;flex-direction:column;gap:12px;margin:0;padding:0;list-style:none}.import-guide li{display:flex;flex-direction:column;gap:3px}.import-guide li b{color:var(--nvr-text);font-size:10px}.import-guide li span,.import-guide p{color:#69778a;font-size:9px;line-height:1.65}.format-box{margin:16px 0 10px;padding:10px;border:1px solid var(--nvr-border);border-radius:8px;background:#0b1118}.format-box code,.import-guide p code{color:#9fb8df;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:9px}.example-button{width:100%;height:32px;border:1px solid var(--nvr-border-strong);border-radius:7px;color:#b8c4d1;background:var(--nvr-surface-2);cursor:pointer;font-size:10px}.example-button:hover{border-color:rgba(76,141,255,.4);color:#dce7f5}.import-guide p{margin:14px 0 0}
.import-editor{min-width:0;padding:16px 18px}.editor-head{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:10px}.editor-head>div:first-child{display:flex;min-width:0;flex-direction:column;gap:3px}.editor-head strong{font-size:11px}.editor-head span{color:var(--nvr-muted);font-size:9px}.parse-state{display:flex;align-items:center;gap:10px;white-space:nowrap}.parse-state span{display:inline-flex;align-items:center;gap:5px}.parse-state :deep(svg){width:12px}.parse-state .valid{color:var(--nvr-green)}.parse-state .invalid{color:var(--nvr-red)}.batch-textarea :deep(textarea){min-height:290px!important;padding:12px 13px!important;color:#bdc9d6!important;background:#0b1118!important;font-family:ui-monospace,SFMono-Regular,Menlo,monospace!important;font-size:10px!important;line-height:1.7!important}
.validation-panel{margin-top:10px;padding:10px 12px;border:1px solid var(--nvr-border);border-radius:8px;background:var(--nvr-surface-2)}.validation-panel.danger{border-color:rgba(240,93,94,.22);background:rgba(240,93,94,.04)}.validation-panel.success{border-color:rgba(46,204,138,.2);background:rgba(46,204,138,.04)}.validation-title{display:flex;align-items:center;gap:6px;margin-bottom:7px;font-size:10px}.validation-title :deep(svg){width:13px}.danger .validation-title{color:var(--nvr-red)}.success .validation-title{color:var(--nvr-green)}.validation-list{max-height:105px;display:flex;flex-direction:column;gap:4px;overflow:auto;color:#b88788;font-size:9px}.result-line{display:flex;align-items:center;gap:14px;flex-wrap:wrap;color:#9db4a9;font-size:9px}.result-line b{color:var(--nvr-green);font-size:11px}.result-line .skipped{width:100%;color:var(--nvr-muted)}
.import-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 18px;border-top:1px solid var(--nvr-border);background:#10161e}.footer-note{color:#66758a;font-size:9px}.footer-actions{display:flex;align-items:center;gap:8px}
@media(max-width:760px){.import-hero{grid-template-columns:auto 1fr}.import-hero>.el-switch{grid-column:1/-1;justify-self:start}.import-layout{grid-template-columns:1fr}.import-guide{border-right:0;border-bottom:1px solid var(--nvr-border)}.import-guide ol{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}.import-footer{align-items:stretch;flex-direction:column}.footer-actions{justify-content:flex-end}}
</style>
