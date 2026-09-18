export type CameraDiscoveryAdapter = 'manual_rtsp' | 'onvif'

export interface OnvifDiscoveryCandidate {
  endpoint_reference?: string | null
  xaddrs: string[]
  scopes: string[]
  device_service_url?: string | null
  host?: string | null
  port?: number | null
  selectable: boolean
  unavailable_reason?: string | null
}

export interface OnvifDiscoveryResponse {
  devices: OnvifDiscoveryCandidate[]
  scan_duration_ms: number
  warnings: string[]
}

export interface RtspDiscoveryCandidate {
  host: string
  port: number
  selectable: boolean
}

export interface RtspDiscoveryResponse {
  network: string
  devices: RtspDiscoveryCandidate[]
  scan_duration_ms: number
  warnings: string[]
}

export type CameraDiscoverySelection =
  | {
      adapter: 'manual_rtsp'
      host: string
      port: 554
    }
  | {
      adapter: 'onvif'
      host: string
      port: number
      device_service_url: string
    }
