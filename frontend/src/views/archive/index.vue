<template>
  <section class="page" data-module="archive">
    <header class="page-head">
      <div>
        <h2>资料归档管理</h2>
        <p class="page-desc">按区段与车站归档图纸、竣工资料，带版本号与生效日期；换版后旧版本只能查看，资料可按区段打包取走。</p>
      </div>
      <div class="page-actions">
        <select v-model="packageSection" class="btn" title="选择要打包的区段">
          <option v-for="item in ledgerSections" :key="item.区段编码" :value="item.区段编码">
            {{ item.区段编码 }} · {{ item.区段名称 }}
          </option>
        </select>
        <button class="btn" type="button" @click="downloadPackage">按区段打包取走</button>
        <button class="btn primary" type="button" @click="toggleUpload">上传资料</button>
        <button class="btn" type="button" @click="exportRows">导出归档清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div v-if="showUpload" class="panel">
      <h3>批量上传（一次可传多份，先校验、确认后才入库）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>资料名称</th><th>资料类别</th><th>所属区段</th><th>所属车站</th>
            <th>版本号</th><th>生效日期</th><th>文件名</th><th>上传人</th><th>文件内容</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in uploadRows" :key="index">
            <td><input v-model="row.资料名称" placeholder="如：信号平面布置图" /></td>
            <td>
              <select v-model="row.资料类别">
                <option v-for="item in categories" :key="item" :value="item">{{ item }}</option>
              </select>
            </td>
            <td>
              <select v-model="row.所属区段">
                <option v-for="item in ledgerSections" :key="item.区段编码" :value="item.区段编码">
                  {{ item.区段编码 }}
                </option>
              </select>
            </td>
            <td><input v-model="row.所属车站" placeholder="如：中心车站" /></td>
            <td><input v-model="row.版本号" placeholder="V1.0" /></td>
            <td><input v-model="row.生效日期" type="date" /></td>
            <td><input v-model="row.文件名" placeholder="xxx.pdf" /></td>
            <td><input v-model="row.上传人" /></td>
            <td><input v-model="row.文件内容" placeholder="可选" /></td>
            <td><button class="link" type="button" @click="uploadRows.splice(index, 1)">删除</button></td>
          </tr>
        </tbody>
      </table>
      <div class="panel-actions">
        <button class="btn" type="button" @click="addUploadRow">添加一行</button>
        <button class="btn primary" type="button" @click="validateUpload">校验上传内容</button>
        <button class="btn ghost" type="button" @click="discardUpload">放弃本次上传</button>
      </div>

      <div v-if="validation" class="panel">
        <h3>
          校验结果：可入库 {{ validation.可入库.length }} 份 / 未通过 {{ validation.未通过.length }} 份
          / 重复忽略 {{ validation.重复忽略.length }} 份
        </h3>
        <p v-if="validation.批次号" class="page-desc">
          批次 {{ validation.批次号 }}，{{ validation.批次有效期分钟 }} 分钟内确认有效；确认前不会写入归档。
        </p>
        <template v-if="validation.未通过.length">
          <h4>未通过（单独列出，修正后重新校验）</h4>
          <table class="data-table">
            <thead><tr><th>序号</th><th>资料名称</th><th>文件名</th><th>未通过原因</th></tr></thead>
            <tbody>
              <tr v-for="item in validation.未通过" :key="item.序号">
                <td>{{ item.序号 }}</td>
                <td>{{ item.资料名称 }}</td>
                <td>{{ item.文件名 }}</td>
                <td>{{ item.原因.join('；') }}</td>
              </tr>
            </tbody>
          </table>
        </template>
        <template v-if="validation.重复忽略.length">
          <h4>重复忽略（同一份图纸只留一条）</h4>
          <table class="data-table">
            <thead><tr><th>序号</th><th>资料名称</th><th>版本号</th><th>忽略原因</th></tr></thead>
            <tbody>
              <tr v-for="item in validation.重复忽略" :key="item.序号">
                <td>{{ item.序号 }}</td>
                <td>{{ item.资料名称 }}</td>
                <td>{{ item.版本号 }}</td>
                <td>{{ item.原因 }}</td>
              </tr>
            </tbody>
          </table>
        </template>
        <template v-if="validation.可入库.length">
          <h4>可入库（确认后写入归档）</h4>
          <table class="data-table">
            <thead><tr><th>序号</th><th>资料名称</th><th>资料类别</th><th>所属区段</th><th>所属车站</th><th>版本号</th><th>生效日期</th></tr></thead>
            <tbody>
              <tr v-for="item in validation.可入库" :key="item.序号">
                <td>{{ item.序号 }}</td>
                <td>{{ item.资料名称 }}</td>
                <td>{{ item.资料类别 }}</td>
                <td>{{ item.所属区段 }}</td>
                <td>{{ item.所属车站 }}</td>
                <td>{{ item.版本号 }}</td>
                <td>{{ item.生效日期 }}</td>
              </tr>
            </tbody>
          </table>
        </template>
        <div class="panel-actions">
          <button v-if="validation.批次号" class="btn primary" type="button" @click="confirmUpload">确认入库</button>
          <span v-else class="page-desc">没有可入库的条目，请修正未通过项后重新校验</span>
        </div>
      </div>
    </div>

    <div v-if="detail" class="panel">
      <h3>资料明细 · {{ detail.资料编号 }}（{{ detail.资料状态 }}）</h3>
      <p class="page-desc">
        {{ detail.资料名称 }} · {{ detail.资料类别 }} · {{ detail.所属区段 }} · {{ detail.所属车站 }} ·
        {{ detail.版本号 }} · 生效 {{ detail.生效日期 }} · {{ detail.文件名 }} ·
        上传人 {{ detail.上传人 }} · {{ detail.上传时间 }}
        <template v-if="detail.备注"> · 备注：{{ detail.备注 }}</template>
      </p>
      <h4>版本沿革（旧版本仅可查看，不能下载）</h4>
      <table class="data-table">
        <thead><tr><th>资料编号</th><th>版本号</th><th>生效日期</th><th>资料状态</th><th>上传人</th><th>上传时间</th></tr></thead>
        <tbody>
          <tr v-for="item in versions" :key="String(item.id)">
            <td>{{ item.资料编号 }}</td>
            <td>{{ item.版本号 }}</td>
            <td>{{ item.生效日期 }}</td>
            <td>{{ item.资料状态 }}</td>
            <td>{{ item.上传人 }}</td>
            <td>{{ item.上传时间 }}</td>
          </tr>
        </tbody>
      </table>
      <div class="panel-actions">
        <button class="btn ghost" type="button" @click="detail = null">收起明细</button>
      </div>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>资料名称</span>
        <input v-model="filters.keyword" placeholder="按资料名称检索" />
      </label>
      <label class="filter-item">
        <span>所属区段</span>
        <select v-model="filters.section">
          <option value="">全部区段</option>
          <option v-for="item in ledgerSections" :key="item.区段编码" :value="item.区段编码">
            {{ item.区段编码 }} · {{ item.区段名称 }}
          </option>
        </select>
      </label>
      <label class="filter-item">
        <span>资料类别</span>
        <select v-model="filters.category">
          <option value="">全部类别</option>
          <option v-for="item in categories" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>资料状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="viewDetail(row)">查看</button>
            <button v-if="row.可下载" class="link" type="button" @click="downloadRow(row)">下载</button>
            <span v-else class="muted-text">仅查看</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无归档资料，可点击「上传资料」批量归档</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条归档资料记录</span>
      <span v-if="noticeMessage" class="ok-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>
type LedgerSection = { 区段编码: string; 区段名称: string; 所属线路: string }
type UploadRow = {
  资料名称: string
  资料类别: string
  所属区段: string
  所属车站: string
  版本号: string
  生效日期: string
  文件名: string
  上传人: string
  文件内容: string
}
type RejectedItem = { 序号: number; 资料名称: string; 文件名: string; 原因: string[] }
type DuplicateItem = { 序号: number; 资料名称: string; 版本号: string; 原因: string }
type AcceptedItem = {
  序号: number
  资料名称: string
  资料类别: string
  所属区段: string
  所属车站: string
  版本号: string
  生效日期: string
  文件名: string
}
type Validation = {
  批次号: string | null
  可入库: AcceptedItem[]
  未通过: RejectedItem[]
  重复忽略: DuplicateItem[]
  批次有效期分钟: number
}

const ENDPOINT = '/api/archive'
const columns = ['资料编号', '资料名称', '资料类别', '所属区段', '所属车站', '版本号', '生效日期', '文件格式', '上传人', '资料状态']

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([{ label: '归档资料', value: 0 }, { label: '现行有效', value: 0 }, { label: '历史版本', value: 0 }, { label: '覆盖区段', value: 0 }])
const ledgerSections = ref<LedgerSection[]>([])
const categories = ref<string[]>(['图纸', '竣工资料'])
const statuses = ref<string[]>(['现行有效', '历史版本'])
const filters = ref<Record<string, string>>({})
const packageSection = ref('')
const errorMessage = ref('')
const noticeMessage = ref('')

const showUpload = ref(false)
const uploadRows = ref<UploadRow[]>([])
const validation = ref<Validation | null>(null)
const detail = ref<Row | null>(null)
const versions = ref<Row[]>([])

function emptyUploadRow(): UploadRow {
  return {
    资料名称: '',
    资料类别: categories.value[0] ?? '图纸',
    所属区段: ledgerSections.value[0]?.区段编码 ?? '',
    所属车站: '',
    版本号: '',
    生效日期: '',
    文件名: '',
    上传人: session.operator,
    文件内容: '',
  }
}

function addUploadRow() {
  uploadRows.value.push(emptyUploadRow())
}

function toggleUpload() {
  if (showUpload.value && validation.value?.批次号) {
    // 面板里还有没确认的批次：关掉面板等于中断上传，暂存批次直接放弃，不留半份资料
    void discardBatch(validation.value.批次号)
  }
  showUpload.value = !showUpload.value
  validation.value = null
  if (showUpload.value && !uploadRows.value.length) {
    addUploadRow()
  }
}

function resetUpload() {
  showUpload.value = false
  validation.value = null
  uploadRows.value = []
}

async function validateUpload() {
  errorMessage.value = ''
  noticeMessage.value = ''
  const items = uploadRows.value.filter((row) => Object.values(row).some((value) => value.trim()))
  if (!items.length) {
    errorMessage.value = '请先填写要上传的资料条目'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/uploads/validate`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload?.detail ?? '校验请求失败，请稍后重试')
    }
    validation.value = payload as Validation
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '校验请求失败'
  }
}

async function confirmUpload() {
  const batchId = validation.value?.批次号
  if (!batchId) {
    return
  }
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/uploads/${batchId}/confirm`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.message ?? payload?.detail ?? '确认入库失败')
    }
    noticeMessage.value = payload.message
    resetUpload()
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '确认入库失败'
  }
}

async function discardBatch(batchId: string) {
  await request(`${ENDPOINT}/uploads/${batchId}`, { method: 'DELETE' }).catch(() => undefined)
}

async function discardUpload() {
  if (validation.value?.批次号) {
    await discardBatch(validation.value.批次号)
  }
  resetUpload()
  noticeMessage.value = '本次上传已放弃，未写入任何资料'
}

async function viewDetail(row: Row) {
  errorMessage.value = ''
  try {
    const [detailResp, versionsResp] = await Promise.all([
      request(`${ENDPOINT}/${row.id}`),
      request(`${ENDPOINT}/${row.id}/versions`),
    ])
    if (!detailResp.ok || !versionsResp.ok) {
      throw new Error('资料明细读取失败')
    }
    detail.value = (await detailResp.json()) as Row
    versions.value = ((await versionsResp.json()).items ?? []) as Row[]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资料明细读取失败'
  }
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

async function downloadRow(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/download`)
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.detail ?? '资料下载失败')
    }
    saveBlob(await response.blob(), String(row.文件名 ?? `${row.资料编号}.txt`))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资料下载失败'
  }
}

async function downloadPackage() {
  errorMessage.value = ''
  noticeMessage.value = ''
  if (!packageSection.value) {
    errorMessage.value = '请先选择要打包的区段'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/package?section=${encodeURIComponent(packageSection.value)}`)
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.detail ?? '打包下载失败')
    }
    saveBlob(await response.blob(), `资料打包-${packageSection.value}.zip`)
    noticeMessage.value = `区段 ${packageSection.value} 的现行资料已打包取走`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '打包下载失败'
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(Object.entries(filters.value).filter(([, value]) => value)).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('资料归档列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资料归档列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}?size=200`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    const all = (payload.items ?? []) as Row[]
    stats.value = [
      { label: '归档资料', value: all.length },
      { label: '现行有效', value: all.filter((row) => row.资料状态 === '现行有效').length },
      { label: '历史版本', value: all.filter((row) => row.资料状态 === '历史版本').length },
      { label: '覆盖区段', value: new Set(all.map((row) => row.所属区段)).size },
    ]
  } catch {
    // 统计卡片读取失败不挡列表
  }
}

async function loadLedger() {
  try {
    const response = await request(`${ENDPOINT}/sections`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    ledgerSections.value = payload.items ?? []
    categories.value = payload.categories ?? categories.value
    statuses.value = payload.statuses ?? statuses.value
    packageSection.value = ledgerSections.value[0]?.区段编码 ?? ''
  } catch {
    // 台账读取失败时上传面板仍可手填区段编码
  }
}

onMounted(async () => {
  await Promise.all([reload(), loadStats(), loadLedger()])
})
</script>
