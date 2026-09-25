import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '@/views/Dashboard.vue'
const Section = () => import('@/views/section/index.vue')
const Signal = () => import('@/views/signal/index.vue')
const Switch = () => import('@/views/switch/index.vue')
const Track = () => import('@/views/track/index.vue')
const Interlock = () => import('@/views/interlock/index.vue')
const Atp = () => import('@/views/atp/index.vue')
const Plan = () => import('@/views/plan/index.vue')
const Task = () => import('@/views/task/index.vue')
const Fault = () => import('@/views/fault/index.vue')
const Dispose = () => import('@/views/dispose/index.vue')
const Spare = () => import('@/views/spare/index.vue')
const Measure = () => import('@/views/measure/index.vue')
const Patrol = () => import('@/views/patrol/index.vue')
const Window = () => import('@/views/window/index.vue')
const Alarm = () => import('@/views/alarm/index.vue')
const Verify = () => import('@/views/verify/index.vue')
const Shift = () => import('@/views/shift/index.vue')
const Assess = () => import('@/views/assess/index.vue')
const Archive = () => import('@/views/archive/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/section', name: 'section', component: Section },
    { path: '/signal', name: 'signal', component: Signal },
    { path: '/switch', name: 'switch', component: Switch },
    { path: '/track', name: 'track', component: Track },
    { path: '/interlock', name: 'interlock', component: Interlock },
    { path: '/atp', name: 'atp', component: Atp },
    { path: '/plan', name: 'plan', component: Plan },
    { path: '/task', name: 'task', component: Task },
    { path: '/fault', name: 'fault', component: Fault },
    { path: '/dispose', name: 'dispose', component: Dispose },
    { path: '/spare', name: 'spare', component: Spare },
    { path: '/measure', name: 'measure', component: Measure },
    { path: '/patrol', name: 'patrol', component: Patrol },
    { path: '/window', name: 'window', component: Window },
    { path: '/alarm', name: 'alarm', component: Alarm },
    { path: '/verify', name: 'verify', component: Verify },
    { path: '/shift', name: 'shift', component: Shift },
    { path: '/assess', name: 'assess', component: Assess },
    { path: '/archive', name: 'archive', component: Archive },
  ],
})

export default router
