import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/nvr-theme.css'
import './styles/recording-browser.css'
import './styles/health-workspace.css'
import './styles/playback-metrics.css'

import Root from './Root.vue'

document.documentElement.classList.add('dark')

const app = createApp(Root)

app.use(createPinia())
app.use(ElementPlus)
app.mount('#app')
