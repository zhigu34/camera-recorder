import axios from 'axios'

import {
  DEFAULT_APPLICATION_TIME_ZONE,
  configureApplicationTimeZone,
} from './dateTime'

interface RuntimeBootstrapSettings {
  timezone?: string
}

export async function bootstrapApplicationTimeZone() {
  try {
    const { data } = await axios.get<RuntimeBootstrapSettings>('/api/settings/runtime', { timeout: 1500 })
    return configureApplicationTimeZone(data.timezone || DEFAULT_APPLICATION_TIME_ZONE)
  } catch {
    return configureApplicationTimeZone(DEFAULT_APPLICATION_TIME_ZONE)
  }
}
