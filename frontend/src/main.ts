import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import Root from './Root.vue'

const app = createApp(Root)

app.use(createPinia())
app.use(ElementPlus)
app.mount('#app')
