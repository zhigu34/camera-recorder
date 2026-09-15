import type { ReliabilityConfidence, ReliabilityVerdict } from '../stores/healthReliability'

export function formatBytes(value?: number | null) {
  const bytes = Math.max(0, Number(value || 0))
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(2)} TB`
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

export function formatDuration(value?: number | null) {
  const seconds = Math.max(0, Math.floor(Number(value || 0)))
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days) return `${days}天 ${hours}小时`
  if (hours) return `${hours}小时 ${minutes}分`
  if (minutes) return `${minutes}分`
  return `${seconds}秒`
}

export function formatTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export function formatRate(value?: number | null) {
  return value === null || value === undefined ? '-' : `${value.toFixed(2)}%`
}

export function rateType(value?: number | null) {
  if (value === null || value === undefined) return 'info'
  if (value >= 99.9) return 'success'
  if (value >= 99) return 'warning'
  return 'danger'
}

export function verdictLabel(value: ReliabilityVerdict) {
  if (value === 'pass') return '通过'
  if (value === 'fail') return '未通过'
  if (value === 'collecting') return '采集中'
  return '未监控'
}

export function verdictType(value: ReliabilityVerdict) {
  if (value === 'pass') return 'success'
  if (value === 'fail') return 'danger'
  if (value === 'collecting') return 'warning'
  return 'info'
}

export function confidenceLabel(value: ReliabilityConfidence | string) {
  if (value === 'high') return '高置信度'
  if (value === 'medium') return '中置信度'
  return '低置信度'
}

export function connectivityLabel(value: string) {
  if (value === 'online') return '在线'
  if (value === 'offline') return '离线'
  return '未检测'
}

export function recorderLabel(value: string) {
  if (value === 'RECORDING') return '录像中'
  if (value === 'STARTING') return '启动中'
  if (value === 'RECONNECTING') return '重连中'
  if (value === 'STOPPING') return '停止中'
  return '未录像'
}

export function scheduleLabel(value: string) {
  if (value === 'automatic') return '自动录像'
  if (value === 'in_window') return '计划时段内'
  if (value === 'scheduled') return '等待计划时段'
  if (value === 'manual_override') return '手动运行'
  if (value === 'manual_paused') return '手动暂停'
  if (value === 'probe_required') return '需要检测参数'
  if (value === 'error') return '计划启动失败'
  if (value === 'global_disabled') return '全局自动启动关闭'
  return '未启用自动录像'
}
