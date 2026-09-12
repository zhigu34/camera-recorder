import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

// Style ownership: tokens -> shared component system -> product shell -> page refinements.
import './styles/nvr-theme.css'
import './styles/appliance-console.css'
import './styles/unifi-console.css'
import './styles/recording-browser.css'
import './styles/recording-browser-theme.css'
import './styles/health-workspace.css'
import './styles/recording-management.css'
import './styles/playback-metrics.css'
import './styles/system-settings.css'
import './styles/camera-device-center.css'
import './styles/camera-device-layout.css'
import './styles/camera-detail-drawer.css'

import Root from './Root.vue'
import { router } from './router'

type ThemeMode = 'light' | 'dark'

function initialTheme(): ThemeMode {
  const stored = localStorage.getItem('nvr-theme')
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

const theme = initialTheme()
document.documentElement.dataset.theme = theme
document.documentElement.classList.toggle('dark', theme === 'dark')

const app = createApp(Root)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(ElementPlus)
app.mount('#app')
