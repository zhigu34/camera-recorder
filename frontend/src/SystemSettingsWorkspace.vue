<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, Setting } from '@element-plus/icons-vue'
import AlertSettingsView from './AlertSettingsView.vue'
import SystemSettingsView from './SystemSettingsView.vue'

const emit = defineEmits<{
  (event: 'open-events'): void
}>()

const route = useRoute()
const router = useRouter()
const activeSection = ref<'system' | 'alerts'>('system')

async function syncFromRoute() {
  const raw = Array.isArray(route.query.section) ? route.query.section[0] : route.query.section
  const section = raw || 'system'
  activeSection.value = section === 'alerts' ? 'alerts' : 'system'
  if (section === 'archive') {
    await nextTick()
    document.getElementById('archive-settings')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

function setSection(section: 'system' | 'alerts') {
  activeSection.value = section
  const query = section === 'alerts' ? { section: 'alerts' } : {}
  void router.replace({ path: '/settings', query })
}

watch(() => route.query.section, () => { void syncFromRoute() })
onMounted(() => { void syncFromRoute() })
</script>

<template>
  <section class="settings-shell">
    <div class="settings-local-nav" role="tablist" aria-label="系统设置分类">
      <button role="tab" :aria-selected="activeSection === 'system'" :class="{ active: activeSection === 'system' }" @click="setSection('system')">
        <Setting />
        <span><strong>系统配置</strong><small>录像、磁盘与 OpenList</small></span>
      </button>
      <button role="tab" :aria-selected="activeSection === 'alerts'" :class="{ active: activeSection === 'alerts' }" @click="setSection('alerts')">
        <Bell />
        <span><strong>通知与告警</strong><small>告警策略与邮件服务器</small></span>
      </button>
    </div>

    <SystemSettingsView v-if="activeSection === 'system'" />
    <AlertSettingsView v-else @open-events="emit('open-events')" />
  </section>
</template>

<style scoped>
.settings-shell{width:100%;min-width:0}.settings-local-nav{max-width:1380px;display:flex;align-items:center;gap:2px;margin:14px auto 0;padding:0 22px;border-bottom:1px solid var(--nvr-border)}.settings-local-nav button{appearance:none;position:relative;display:flex;align-items:center;gap:8px;min-height:44px;padding:0 12px;border:0;color:var(--nvr-muted);background:transparent;cursor:pointer;text-align:left;transition:color .14s ease,background-color .14s ease}.settings-local-nav button:hover{color:var(--nvr-text-soft);background:color-mix(in srgb,var(--nvr-hover) 62%,transparent)}.settings-local-nav button.active{color:var(--nvr-text)}.settings-local-nav button.active::after{content:'';position:absolute;left:12px;right:12px;bottom:-1px;height:2px;border-radius:999px;background:var(--nvr-blue)}.settings-local-nav button>svg{flex:0 0 15px;width:15px}.settings-local-nav button>span{display:flex;min-width:0;flex-direction:column;gap:2px}.settings-local-nav strong{font-size:11px;font-weight:620}.settings-local-nav small{color:var(--nvr-subtle);font-size:9px}.settings-local-nav button.active small{color:var(--nvr-muted)}
.settings-shell :deep(.alert-page){max-width:1380px;margin:0 auto}.settings-shell :deep(.alert-page .status-grid){grid-template-columns:repeat(4,minmax(0,1fr))}.settings-shell :deep(.alert-page .settings-layout){gap:10px}
@media(max-width:1000px){.settings-shell :deep(.alert-page .status-grid){grid-template-columns:repeat(2,minmax(0,1fr))}.settings-shell :deep(.alert-page .settings-layout){grid-template-columns:1fr}}
@media(max-width:720px){.settings-local-nav{gap:0;margin-top:8px;padding:0 14px}.settings-local-nav button{min-width:0;flex:1;padding:0 8px}.settings-local-nav button.active::after{left:8px;right:8px}.settings-local-nav small{display:none}.settings-shell :deep(.alert-page){padding:14px}.settings-shell :deep(.alert-page .status-grid){grid-template-columns:1fr 1fr}}
</style>
