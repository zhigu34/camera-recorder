export const DEFAULT_APPLICATION_TIME_ZONE = 'Asia/Shanghai'

const DISPLAY_DATETIME = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/
const NAIVE_ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/

let configuredTimeZone = DEFAULT_APPLICATION_TIME_ZONE

function validTimeZone(value: string) {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: value }).format(0)
    return true
  } catch {
    return false
  }
}

export function configureApplicationTimeZone(timeZone: string) {
  const candidate = timeZone.trim()
  configuredTimeZone = candidate && validTimeZone(candidate)
    ? candidate
    : DEFAULT_APPLICATION_TIME_ZONE
  return configuredTimeZone
}

export function applicationTimeZone() {
  return configuredTimeZone
}

export function formatDateTime(value?: string | Date | null) {
  if (!value) return '-'
  if (typeof value === 'string' && DISPLAY_DATETIME.test(value)) return value

  let parsed: Date
  if (value instanceof Date) parsed = value
  else if (NAIVE_ISO.test(value)) parsed = new Date(`${value}Z`)
  else parsed = new Date(value)

  if (Number.isNaN(parsed.getTime())) return typeof value === 'string' ? value : '-'

  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: configuredTimeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(parsed)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}:${values.second}`
}
