const PREFIXES: Array<[string, string]> = [
  ['onvif://www.onvif.org/name/', '名称'],
  ['onvif://www.onvif.org/location/', '位置'],
  ['onvif://www.onvif.org/hardware/', '硬件'],
]

export function scopeLabel(scope: string): string {
  for (const [prefix, label] of PREFIXES) {
    if (!scope.startsWith(prefix)) continue
    const raw = scope.slice(prefix.length)
    try {
      return `${label}：${decodeURIComponent(raw)}`
    } catch {
      return `${label}：${raw}`
    }
  }
  return scope
}
