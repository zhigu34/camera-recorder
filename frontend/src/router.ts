import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const WorkspaceRoute = () => import('./WorkspaceRoute.vue')

const routes: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: WorkspaceRoute, meta: { navKey: 'dashboard' } },
  { path: '/preview', name: 'preview', component: WorkspaceRoute, meta: { navKey: 'preview' } },
  {
    path: '/recordings/browser',
    redirect: (to) => ({ path: '/recordings/playback', query: to.query, hash: to.hash }),
  },
  {
    path: '/recordings/playback',
    name: 'recordings-playback',
    component: WorkspaceRoute,
    meta: { navKey: 'recordings', recordingMode: 'playback' },
  },
  {
    path: '/recordings/manage',
    name: 'recordings-manage',
    component: WorkspaceRoute,
    meta: { navKey: 'recordings', recordingMode: 'manage' },
  },
  { path: '/cameras', name: 'cameras', component: WorkspaceRoute, meta: { navKey: 'cameras' } },
  { path: '/cameras/batch', name: 'camera-batch', component: WorkspaceRoute, meta: { navKey: 'cameras' } },
  { path: '/recording-schedules', name: 'schedule', component: WorkspaceRoute, meta: { navKey: 'schedule' } },
  { path: '/health-center', name: 'health', component: WorkspaceRoute, meta: { navKey: 'health' } },
  { path: '/uploads', name: 'uploads', component: WorkspaceRoute, meta: { navKey: 'uploads' } },
  { path: '/events', name: 'events', component: WorkspaceRoute, meta: { navKey: 'events' } },
  { path: '/settings', name: 'settings', component: WorkspaceRoute, meta: { navKey: 'settings' } },
  { path: '/alerts', redirect: { path: '/settings', query: { section: 'alerts' } } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, behavior: 'smooth' }
    if (to.path !== from.path) return { top: 0 }
    return false
  },
})
