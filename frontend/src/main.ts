import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/nvr-theme.css'
import './styles/recording-browser.css'
import './styles/health-workspace.css'
import './styles/playback-metrics.css'
import './styles/system-settings.css'

import Root from './Root.vue'

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

app.use(createPinia())
app.use(ElementPlus)
app.mount('#app')
