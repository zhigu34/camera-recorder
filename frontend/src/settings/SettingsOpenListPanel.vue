<script setup lang="ts">
import { computed } from 'vue'
import { TopRight } from '@element-plus/icons-vue'
import type { RuntimeSettingsDraft } from '../utils/runtimeSettings'
const settings = defineModel<RuntimeSettingsDraft>({ required: true })
const archiveState = computed(() => {
  if (!settings.value.upload_enabled) return { label: '自动归档已关闭', tone: 'muted' }
  if (!settings.value.webdav_url.trim() || !settings.value.webdav_username.trim() || (!settings.value.webdav_password_set && !settings.value.webdav_password)) {
    return { label: 'WebDAV 配置未完成', tone: 'warning' }
  }
  return { label: '自动归档已启用', tone: 'success' }
})
const managementUrl = computed(() => {
  const raw = settings.value.webdav_url.trim()
  try {
    const target = new URL(raw || 'http://openlist:5244/dav')
    const internalHosts = new Set(['openlist', 'localhost', '127.0.0.1', '::1'])
    if (internalHosts.has(target.hostname.toLowerCase())) {
      target.hostname = window.location.hostname
      target.port = String(settings.value.openlist_management_port || 5244)
    }
    target.pathname = '/'; target.search = ''; target.hash = ''; target.username = ''; target.password = ''
    return target.toString()
  } catch {
    const target = new URL(window.location.origin)
    target.port = String(settings.value.openlist_management_port || 5244)
    target.pathname = '/'; target.search = ''; target.hash = ''
    return target.toString()
  }
})
function openOpenList() { window.open(managementUrl.value, '_blank', 'noopener,noreferrer') }
function passwordChanged(value: string) { if (value) settings.value.clear_webdav_password = false }
</script>

<template>
  <section class="settings-section-page">
    <header class="settings-section-header settings-section-header-with-state">
      <div><span class="settings-section-kicker">ARCHIVE</span><h2>OpenList</h2><p>独立管理 WebDAV 归档入口、凭据和上传策略。</p></div>
      <span class="settings-state-badge" :class="archiveState.tone">{{ archiveState.label }}</span>
    </header>
    <div class="settings-group">
      <div class="settings-group-title settings-group-title-actions">
        <div><strong>服务入口</strong><span>打开当前部署对应的 OpenList 管理界面。</span></div>
        <el-button plain @click="openOpenList">打开 OpenList<el-icon class="external-link-icon"><TopRight /></el-icon></el-button>
      </div>
    </div>
    <div class="settings-group">
      <div class="settings-group-title"><strong>WebDAV 连接</strong><span>Camera Recorder 只依赖标准 WebDAV，不绑定具体网盘品牌。</span></div>
      <div class="setting-row">
        <div class="setting-copy"><strong>WebDAV 地址</strong><span>可填写 WebDAV 根地址，也可直接指向某个挂载目录。</span><em class="activation-pill immediate">保存后生效</em></div>
        <div class="setting-control"><el-input v-model="settings.webdav_url" placeholder="http://openlist:5244/dav" /></div>
      </div>
      <div class="setting-row">
        <div class="setting-copy"><strong>远端归档目录</strong><span>例如“监控录像”或“挂载名/监控录像”。</span><em class="activation-pill immediate">保存后生效</em></div>
        <div class="setting-control"><el-input v-model="settings.webdav_root" placeholder="监控录像" /></div>
      </div>
      <div class="setting-row">
        <div class="setting-copy"><strong>WebDAV 用户名</strong><span>用于后端上传任务连接远端 WebDAV。</span><em class="activation-pill immediate">保存后生效</em></div>
        <div class="setting-control"><el-input v-model="settings.webdav_username" autocomplete="username" /></div>
      </div>
      <div class="setting-row">
        <div class="setting-copy"><strong>WebDAV 密码</strong><span>{{ settings.webdav_password_set ? '已有加密凭据；留空保持当前密码不变。' : '尚未保存 WebDAV 密码。' }}</span><em class="activation-pill immediate">保存后生效</em></div>
        <div class="setting-control password-control">
          <el-input v-model="settings.webdav_password" type="password" show-password autocomplete="new-password" :placeholder="settings.webdav_password_set ? '已加密保存；留空保持不变' : '请输入 WebDAV 密码'" @input="passwordChanged" />
          <div v-if="settings.webdav_password_set" class="password-actions"><el-tag type="success" size="small">凭据已保存</el-tag><el-checkbox v-model="settings.clear_webdav_password">清除已保存密码</el-checkbox></div>
        </div>
      </div>
    </div>
    <div class="settings-group">
      <div class="settings-group-title"><strong>上传策略</strong><span>控制录像文件自动归档的任务并发和失败重试。</span></div>
      <div class="setting-row"><div class="setting-copy"><strong>自动归档</strong><span>开启后，符合条件的录像会自动进入 WebDAV 上传队列。</span><em class="activation-pill immediate">保存后生效</em></div><div class="setting-control setting-control-switch"><el-switch v-model="settings.upload_enabled" /></div></div>
      <div class="setting-row"><div class="setting-copy"><strong>上传并发数</strong><span>同时执行的远端上传任务数。</span><em class="activation-pill immediate">后续任务生效</em></div><div class="setting-control setting-number-unit"><el-input-number v-model="settings.upload_concurrency" :min="1" :max="16" /><span>个</span></div></div>
      <div class="setting-row"><div class="setting-copy"><strong>最大重试次数</strong><span>网络或 WebDAV 临时故障时，单个上传任务允许的最大重试次数。</span><em class="activation-pill immediate">后续任务生效</em></div><div class="setting-control setting-number-unit"><el-input-number v-model="settings.upload_retry_max" :min="1" :max="100" /><span>次</span></div></div>
    </div>
    <div class="settings-inline-note"><strong>本地保留策略已移至“存储”</strong><span>OpenList 只负责远端归档连接和上传任务；本地录像生命周期统一在存储设置中管理。</span></div>
  </section>
</template>
