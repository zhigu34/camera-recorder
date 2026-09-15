<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import AlertSettingsView from './AlertSettingsView.vue'
import OperationsView from './OperationsView.vue'
import SettingsAdvancedPanel from './settings/SettingsAdvancedPanel.vue'
import SettingsGeneralPanel from './settings/SettingsGeneralPanel.vue'
import SettingsOpenListPanel from './settings/SettingsOpenListPanel.vue'
import SettingsRecordingPanel from './settings/SettingsRecordingPanel.vue'
import SettingsStoragePanel from './settings/SettingsStoragePanel.vue'
import {
  cloneRuntimeDraft,
  countRuntimeChanges,
  createRuntimeDraft,
  isRuntimeSettingsSection,
  normalizeSettingsSection,
  serializeRuntimePayload,
  validateRuntimeDraft,
  type RuntimeSettingsDraft,
  type SettingsSection,
  type SystemSettingsRead,
} from './utils/runtimeSettings'

const emit = defineEmits<{ (event: 'open-events'): void }>()
const route = useRoute()
const router = useRouter()
const activeSection = ref<SettingsSection>('general')
const runtimeDraft = ref<RuntimeSettingsDraft | null>(null)
const savedDraft = ref<RuntimeSettingsDraft | null>(null)
const runtimeLoading = ref(false)
const runtimeSaving = ref(false)
const runtimeLoadError = ref('')

const navigation: Array<{ key: SettingsSection; glyph: string; title: string; description: string }> = [
  { key: 'general', glyph: '常', title: '常规', description: '系统名称、启动行为' },
  { key: 'recording', glyph: '录', title: '录像', description: '切片、超时、并发' },
  { key: 'storage', glyph: '存', title: '存储', description: '磁盘阈值、保留策略' },
  { key: 'openlist', glyph: '云', title: 'OpenList', description: '远程归档与 WebDAV' },
  { key: 'alerts', glyph: '告', title: '通知与告警', description: '告警规则、通知方式' },
  { key: 'operations', glyph: '运', title: '运维', description: '日志、备份、系统工具' },
  { key: 'advanced', glyph: '高', title: '高级', description: '底层配置边界' },
]

const dirtyCount = computed(() => {
  if (!savedDraft.value || !runtimeDraft.value) return 0
  return countRuntimeChanges(savedDraft.value, runtimeDraft.value)
})
const runtimeDirty = computed(() => dirtyCount.value > 0)
const runtimeSectionActive = computed(() => isRuntimeSettingsSection(activeSection.value))

function errorText(error: unknown, fallback: string) {
  return axios.isAxiosError(error) ? error.response?.data?.detail || error.message : fallback
}
function syncFromRoute() {
  const raw = Array.isArray(route.query.section) ? route.query.section[0] : route.query.section
  activeSection.value = normalizeSettingsSection(raw)
}
function setSection(section: SettingsSection) {
  void router.replace({ path: '/settings', query: section === 'general' ? {} : { section } })
}
async function loadRuntimeSettings() {
  runtimeLoading.value = true
  runtimeLoadError.value = ''
  try {
    const { data } = await axios.get<SystemSettingsRead>('/api/settings')
    const next = createRuntimeDraft(data)
    runtimeDraft.value = next
    savedDraft.value = cloneRuntimeDraft(next)
  } catch (error) {
    runtimeLoadError.value = errorText(error, '加载系统设置失败')
  } finally {
    runtimeLoading.value = false
  }
}
async function saveRuntimeSettings() {
  if (!runtimeDraft.value) return
  const validationError = validateRuntimeDraft(runtimeDraft.value)
  if (validationError) return void ElMessage.error(validationError)
  runtimeSaving.value = true
  try {
    const { data } = await axios.put<SystemSettingsRead>('/api/settings', serializeRuntimePayload(runtimeDraft.value))
    const next = createRuntimeDraft(data)
    runtimeDraft.value = next
    savedDraft.value = cloneRuntimeDraft(next)
    ElMessage.success('系统设置已保存')
  } catch (error) {
    ElMessage.error(errorText(error, '保存系统设置失败'))
  } finally {
    runtimeSaving.value = false
  }
}
function discardRuntimeChanges() {
  if (savedDraft.value) runtimeDraft.value = cloneRuntimeDraft(savedDraft.value)
}
function confirmDiscardChanges() {
  if (!runtimeDirty.value) return true
  return window.confirm(`系统设置还有 ${dirtyCount.value} 项未保存修改，确定放弃并离开吗？`)
}
function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!runtimeDirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

watch(() => route.query.section, syncFromRoute)
onBeforeRouteLeave(() => confirmDiscardChanges())
onMounted(() => {
  syncFromRoute()
  window.addEventListener('beforeunload', handleBeforeUnload)
  void loadRuntimeSettings()
})
onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
</script>

<template>
  <section class="settings-console-shell">
    <div class="settings-console">
      <aside class="settings-console-nav" aria-label="系统设置分类">
        <div class="settings-console-nav-head"><strong>系统设置</strong><span>配置系统参数和功能</span></div>
        <nav>
          <button v-for="item in navigation" :key="item.key" type="button" :class="{ active: activeSection === item.key }" :aria-current="activeSection === item.key ? 'page' : undefined" @click="setSection(item.key)">
            <span class="settings-nav-glyph" aria-hidden="true">{{ item.glyph }}</span>
            <span class="settings-nav-copy"><strong>{{ item.title }}</strong><small>{{ item.description }}</small></span>
          </button>
        </nav>
      </aside>

      <main class="settings-console-content">
        <div v-if="runtimeSectionActive" class="settings-runtime-layout" v-loading="runtimeLoading">
          <div class="settings-runtime-main">
            <div v-if="runtimeLoadError && !runtimeDraft" class="settings-load-error">
              <strong>无法加载系统设置</strong><span>{{ runtimeLoadError }}</span><el-button :loading="runtimeLoading" @click="loadRuntimeSettings">重新加载</el-button>
            </div>
            <template v-else-if="runtimeDraft">
              <SettingsGeneralPanel v-if="activeSection === 'general'" v-model="runtimeDraft" />
              <SettingsRecordingPanel v-else-if="activeSection === 'recording'" v-model="runtimeDraft" />
              <SettingsStoragePanel v-else-if="activeSection === 'storage'" v-model="runtimeDraft" />
              <SettingsOpenListPanel v-else-if="activeSection === 'openlist'" v-model="runtimeDraft" />
            </template>
          </div>
          <aside v-if="runtimeDraft" class="settings-context-rail">
            <section><strong>配置说明</strong><p>运行时配置保存到 SQLite；部署参数和密钥仍由部署环境管理。</p></section>
            <section>
              <strong>生效方式</strong>
              <ul>
                <li><span class="context-dot immediate"></span><div><b>立即生效</b><small>保存后直接用于后续任务。</small></div></li>
                <li><span class="context-dot recorder"></span><div><b>Recorder 生效</b><small>重新建立对应录像会话后使用新参数。</small></div></li>
                <li><span class="context-dot restart"></span><div><b>服务启动生效</b><small>用于下一次后端服务启动行为。</small></div></li>
              </ul>
            </section>
            <section v-if="activeSection === 'recording'"><strong>当前流参数</strong><p>当前 RTSP 超时 {{ runtimeDraft.rtsp_timeout_seconds }} 秒；切片 {{ runtimeDraft.segment_duration_seconds }} 秒。</p></section>
            <section v-if="activeSection === 'openlist'"><strong>归档边界</strong><p>OpenList 负责远端 WebDAV；本地保留时间统一在“存储”中设置。</p></section>
          </aside>
        </div>

        <div v-else-if="activeSection === 'alerts'" class="settings-embedded-page">
          <header class="settings-section-header embedded-header"><span class="settings-section-kicker">ALERTS</span><h2>通知与告警</h2><p>配置事故判定、恢复通知和邮件服务器。</p></header>
          <AlertSettingsView @open-events="emit('open-events')" />
        </div>
        <div v-else-if="activeSection === 'operations'" class="settings-embedded-page">
          <header class="settings-section-header embedded-header"><span class="settings-section-kicker">OPERATIONS</span><h2>运维</h2><p>查看运行状态、日志、备份和系统维护工具。</p></header>
          <OperationsView />
        </div>
        <SettingsAdvancedPanel v-else-if="activeSection === 'advanced'" />

        <div v-if="runtimeDirty" class="settings-runtime-savebar">
          <div class="settings-save-state"><span class="settings-save-dot" aria-hidden="true"></span><strong>已修改 {{ dirtyCount }} 项</strong><small>尚未保存</small></div>
          <div class="settings-save-actions"><el-button :disabled="runtimeSaving" @click="discardRuntimeChanges">放弃修改</el-button><el-button type="primary" :loading="runtimeSaving" @click="saveRuntimeSettings">保存更改</el-button></div>
        </div>
      </main>
    </div>
  </section>
</template>
