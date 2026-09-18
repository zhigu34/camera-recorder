<script setup lang="ts">
import { computed } from 'vue'

import type { OnvifConnectionConfig, OnvifMediaProfile } from './camera-editor/types'
import type { SharedCamera } from './stores/cameras'

const props = defineProps<{
  camera: SharedCamera
}>()

const config = computed<OnvifConnectionConfig | null>(() => {
  const connection = props.camera.connection
  if (!connection || connection.adapter !== 'onvif') return null
  return connection.config as OnvifConnectionConfig
})

const serviceItems = computed(() => {
  const capabilities = config.value?.capabilities || {}
  return [
    { key: 'media_xaddr', label: 'Media', value: capabilities.media_xaddr },
    { key: 'events_xaddr', label: 'Events', value: capabilities.events_xaddr },
    { key: 'ptz_xaddr', label: 'PTZ', value: capabilities.ptz_xaddr },
  ]
})

function textValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function profileRoles(profile: OnvifMediaProfile) {
  const current = config.value
  if (!current) return []
  const roles: string[] = []
  if (current.recording_profile_token === profile.token) roles.push('录像')
  if (current.preview_profile_token === profile.token) roles.push('预览')
  if (current.detection_profile_token === profile.token) roles.push('检测')
  return roles
}

function profileVideo(profile: OnvifMediaProfile) {
  const parts: string[] = []
  if (profile.encoding) parts.push(profile.encoding.toUpperCase())
  if (profile.width && profile.height) parts.push(`${profile.width}×${profile.height}`)
  if (profile.fps) parts.push(`${profile.fps} FPS`)
  return parts.join(' · ') || '未公布视频参数'
}
</script>

<template>
  <section v-if="config" class="detail-section detail-section-v2 onvif-details">
    <div class="detail-heading onvif-details-heading">
      <div>
        <strong>ONVIF 设备能力</strong>
        <span>来自最近一次成功连接检测；Events / PTZ 仅表示设备公布了对应服务地址。</span>
      </div>
      <span class="onvif-verified-state">
        {{ camera.connection?.verification_status === 'verified' ? '已验证' : '等待检测' }}
      </span>
    </div>

    <dl class="detail-grid detail-grid-v2 onvif-identity-grid">
      <div><dt>固件</dt><dd>{{ config.firmware_version || '-' }}</dd></div>
      <div><dt>序列号</dt><dd>{{ config.serial_number || '-' }}</dd></div>
      <div><dt>Hardware ID</dt><dd>{{ config.hardware_id || '-' }}</dd></div>
      <div><dt>Device UUID</dt><dd>{{ config.device_uuid || '-' }}</dd></div>
      <div class="wide"><dt>Device Service</dt><dd class="onvif-mono">{{ config.device_service_url || '-' }}</dd></div>
    </dl>

    <div class="onvif-capability-list" aria-label="ONVIF 服务能力">
      <div
        v-for="service in serviceItems"
        :key="service.key"
        class="onvif-capability-item"
        :class="{ available: textValue(service.value) }"
      >
        <div>
          <strong>{{ service.label }}</strong>
          <span>{{ textValue(service.value) ? '设备已公布服务地址' : '设备未公布服务地址' }}</span>
        </div>
        <code v-if="textValue(service.value)">{{ textValue(service.value) }}</code>
        <b>{{ textValue(service.value) ? '已发现' : '未发现' }}</b>
      </div>
    </div>

    <div class="onvif-profile-section">
      <div class="onvif-profile-heading">
        <strong>Media Profiles</strong>
        <span>{{ config.profiles?.length || 0 }} 个</span>
      </div>
      <div v-if="config.profiles?.length" class="onvif-profile-list">
        <article v-for="profile in config.profiles" :key="profile.token" class="onvif-profile-item">
          <div class="onvif-profile-copy">
            <div class="onvif-profile-title">
              <strong>{{ profile.name || profile.token }}</strong>
              <span v-for="role in profileRoles(profile)" :key="role">{{ role }}</span>
            </div>
            <small>{{ profileVideo(profile) }}</small>
            <code v-if="profile.uri">{{ profile.uri }}</code>
          </div>
          <div class="onvif-profile-token">{{ profile.token }}</div>
        </article>
      </div>
      <div v-else class="onvif-profile-empty">
        执行一次成功的连接检测后，这里会显示设备返回的 Media Profiles。
      </div>
    </div>
  </section>
</template>

<style scoped>
.onvif-details {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.onvif-details-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.onvif-details-heading > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.onvif-details-heading span,
.onvif-profile-heading span,
.onvif-profile-item small,
.onvif-profile-empty,
.onvif-capability-item span {
  color: var(--nvr-muted);
  font-size: 9px;
  line-height: 1.45;
}

.onvif-verified-state {
  flex: 0 0 auto;
  padding: 3px 6px;
  border: 1px solid var(--nvr-border);
  border-radius: 5px;
  color: var(--nvr-text-soft) !important;
  background: var(--nvr-pill-bg);
}

.onvif-mono,
.onvif-profile-item code,
.onvif-capability-item code,
.onvif-profile-token {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.onvif-mono {
  overflow-wrap: anywhere;
}

.onvif-capability-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.onvif-capability-item {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 7px 10px;
  padding: 10px;
  border: 1px solid var(--nvr-border);
  border-radius: 8px;
  background: var(--nvr-surface-2);
}

.onvif-capability-item > div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.onvif-capability-item strong {
  color: var(--nvr-text);
  font-size: 10px;
}

.onvif-capability-item b {
  align-self: start;
  color: var(--nvr-subtle);
  font-size: 9px;
  font-weight: 600;
}

.onvif-capability-item.available b {
  color: var(--nvr-green);
}

.onvif-capability-item code {
  grid-column: 1 / -1;
  overflow: hidden;
  color: var(--nvr-subtle);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.onvif-profile-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.onvif-profile-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.onvif-profile-heading strong {
  color: var(--nvr-text-soft);
  font-size: 10px;
}

.onvif-profile-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.onvif-profile-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 10px;
  border: 1px solid var(--nvr-border);
  border-radius: 8px;
  background: color-mix(in srgb, var(--nvr-surface) 86%, var(--nvr-surface-2));
}

.onvif-profile-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.onvif-profile-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}

.onvif-profile-title strong {
  color: var(--nvr-text);
  font-size: 10px;
}

.onvif-profile-title span {
  padding: 2px 5px;
  border: 1px solid color-mix(in srgb, var(--nvr-blue) 24%, var(--nvr-border));
  border-radius: 4px;
  color: var(--nvr-blue);
  background: color-mix(in srgb, var(--nvr-blue) 6%, var(--nvr-surface));
  font-size: 8px;
}

.onvif-profile-item code {
  max-width: 100%;
  overflow: hidden;
  color: var(--nvr-subtle);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.onvif-profile-token {
  max-width: 180px;
  overflow: hidden;
  color: var(--nvr-subtle);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.onvif-profile-empty {
  padding: 10px;
  border: 1px dashed var(--nvr-border);
  border-radius: 8px;
  background: var(--nvr-surface-2);
}

@media (max-width: 760px) {
  .onvif-capability-list {
    grid-template-columns: 1fr;
  }

  .onvif-profile-item {
    flex-direction: column;
  }

  .onvif-profile-token {
    max-width: 100%;
  }
}
</style>
