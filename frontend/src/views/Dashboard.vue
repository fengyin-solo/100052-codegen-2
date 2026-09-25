<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
    moduleRows.value = [{"name": "线路区段", "created": 0, "pending": 0, "abnormal": 0}, {"name": "信号机", "created": 0, "pending": 0, "abnormal": 0}, {"name": "转辙机", "created": 0, "pending": 0, "abnormal": 0}, {"name": "轨道电路", "created": 0, "pending": 0, "abnormal": 0}, {"name": "联锁设备", "created": 0, "pending": 0, "abnormal": 0}, {"name": "列车防护", "created": 0, "pending": 0, "abnormal": 0}, {"name": "检修计划", "created": 0, "pending": 0, "abnormal": 0}, {"name": "检修任务", "created": 0, "pending": 0, "abnormal": 0}, {"name": "故障登记", "created": 0, "pending": 0, "abnormal": 0}, {"name": "故障处置", "created": 0, "pending": 0, "abnormal": 0}, {"name": "器材领用", "created": 0, "pending": 0, "abnormal": 0}, {"name": "电气测试", "created": 0, "pending": 0, "abnormal": 0}, {"name": "巡视检查", "created": 0, "pending": 0, "abnormal": 0}, {"name": "天窗作业", "created": 0, "pending": 0, "abnormal": 0}, {"name": "监测报警", "created": 0, "pending": 0, "abnormal": 0}, {"name": "验收确认", "created": 0, "pending": 0, "abnormal": 0}, {"name": "值班交接", "created": 0, "pending": 0, "abnormal": 0}, {"name": "状态评估", "created": 0, "pending": 0, "abnormal": 0}, {"name": "资料归档", "created": 0, "pending": 0, "abnormal": 0}]
  }
})
</script>
