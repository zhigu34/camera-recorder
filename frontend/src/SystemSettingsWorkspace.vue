<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Bell, Setting } from '@element-plus/icons-vue'
import AlertSettingsView from './AlertSettingsView.vue'
import SystemSettingsView from './SystemSettingsView.vue'

const emit = defineEmits<{
  (event: 'open-events'): void
}>()

const activeSection = ref<'system' | 'alerts'>('system')

function syncFromUrl() {
  const section = new URLSearchParams(window.location.search).get('section')
  activeSection.value = section === 'alerts' ? 'alerts' : 'system'
}

function setSection(section: 'system' | 'alerts') {
  activeSection.value = section
  const next = section === 'alerts' ? '/settings?section=alerts' : '/settings'
  window.history.replaceState({}, '', next)
}

onMounted(syncFromUrl)
</script>

<template>
  <section class="settings-shell">
    <div class="settings-local-nav">
      <button :class="{ active: activeSection === 'system' }" @click="setSection('system')">
        <Setting />
        <span><strong>系统配置</strong><small>录像、磁盘与 OpenList</small></span>
      </button>
      <button :class="{ active: activeSection === 'alerts' }" @click="setSection('alerts')">
        <Bell />
        <span><strong>通知与告警</strong><small>告警策略与 SMTP</small></span>
      </button>
    </div>

    <SystemSettingsView v-if="activeSection === 'system'" />
    <AlertSettingsView v-else @open-events="emit('open-events')" />
  </section>
</template>

<style scoped>
.settings-shell{width:100%;min-width:0}.settings-local-nav{max-width:1380px;display:grid;grid-template-columns:repeat(2,minmax(0,240px));gap:8px;margin:18px auto -4px;padding:0 22px}.settings-local-nav button{appearance:none;display:flex;align-items:center;gap:10px;min-height:48px;padding:8px 11px;border:1px solid var(--nvr-border);border-radius:9px;color:#7e8c9e;background:#10161e;cursor:pointer;text-align:left;transition:.15s}.settings-local-nav button:hover{border-color:var(--nvr-border-strong);color:#b7c3cf}.settings-local-nav button.active{border-color:rgba(76,141,255,.42);color:var(--nvr-text);background:rgba(76,141,255,.075)}.settings-local-nav button>svg{flex:0 0 17px;width:17px}.settings-local-nav button>span{display:flex;min-width:0;flex-direction:column;gap:2px}.settings-local-nav strong{font-size:10px;font-weight:650}.settings-local-nav small{color:#687689;font-size:8px}
.settings-shell :deep(.alert-page){max-width:1380px;margin:0 auto;padding:18px 22px 28px}.settings-shell :deep(.alert-page .status-grid){grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.settings-shell :deep(.alert-page .status-card){min-height:74px;padding:11px 12px}.settings-shell :deep(.alert-page .status-card strong){font-size:13px}.settings-shell :deep(.alert-page .scope-panel){padding:13px}.settings-shell :deep(.alert-page .scope-grid){gap:8px}.settings-shell :deep(.alert-page .scope-item){min-height:62px;padding:10px}.settings-shell :deep(.alert-page .settings-layout){grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.settings-shell :deep(.alert-page .settings-layout>.panel){padding:13px}.settings-shell :deep(.alert-page .page-actions){margin-bottom:10px}
@media(max-width:1000px){.settings-shell :deep(.alert-page .status-grid){grid-template-columns:repeat(2,minmax(0,1fr))}.settings-shell :deep(.alert-page .settings-layout){grid-template-columns:1fr}}
@media(max-width:720px){.settings-local-nav{grid-template-columns:1fr 1fr;margin-top:10px;padding:0 14px}.settings-local-nav button{min-width:0}.settings-local-nav small{display:none}.settings-shell :deep(.alert-page){padding:14px}.settings-shell :deep(.alert-page .status-grid){grid-template-columns:1fr 1fr}}
</style>
