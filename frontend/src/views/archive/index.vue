<template>
  <section class="page" data-module="archive">
    <header class="page-head">
      <div>
        <h2>资料归档</h2>
        <p class="page-desc">按区段与车站归档图纸、竣工资料，版本号与生效日期随资料留存；竣工资料换版后旧版本只可查看，区段资料可整包取走。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openUpload">上传图纸 / 竣工资料</button>
        <button class="btn" type="button" @click="openPackage">按区段打包取走</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>区段编码</span>
        <select v-model="filters.区段编码">
          <option value="">全部区段</option>
          <option v-for="code in options.区段编码" :key="code" :value="code">{{ code }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>车站</span>
        <select v-model="filters.车站">
          <option value="">全部车站</option>
          <option v-for="name in options.车站" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>资料类型</span>
        <select v-model="filters.资料类型">
          <option value="">全部类型</option>
          <option v-for="t in options.资料类型" :key="t" :value="t">{{ t }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>资料名称</span>
        <input v-model="filters.keyword" placeholder="按资料名称/文件名检索" />
      </label>
      <label class="filter-item checkbox">
        <input v-model="showAll" type="checkbox" @change="reload" />
        <span>含历史版本</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>版本状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ formatCell(row, column) }}</td>
          <td>
            <span :class="row.is_latest ? 'tag latest' : 'tag history'">
              {{ row.is_latest ? '当前生效' : '历史版本' }}
            </span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openVersions(row)">版本沿革</button>
            <button class="link" type="button" @click="viewFile(row)">查看</button>
            <button
              class="link"
              type="button"
              :disabled="!row.可下载"
              :title="row.可下载 ? '下载文件' : '竣工资料旧版本只能查看，不能再下载'"
              @click="downloadFile(row)"
            >
              下载
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无归档资料，点击右上角上传第一批图纸或竣工资料</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ showAll ? '（含历史版本）' : '当前生效版本' }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 上传向导：选文件 → 校验（问题逐条列出）→ 确认入库 -->
    <div v-if="uploadOpen" class="modal-mask" @click.self="closeUpload">
      <div class="modal wide">
        <h3>上传图纸 / 竣工资料</h3>
        <p class="page-desc">一次可选择多份文件；先校验，缺少版本号、格式不对、版本号与资料关联不上的条目会单独列出，确认后才入库。</p>

        <!-- 第一步：编辑待传条目 -->
        <template v-if="step === 'edit'">
          <div class="batch-meta">
            <label class="filter-item">
              <span>区段编码（与设备台账一致）</span>
              <select v-model="batchMeta.区段编码">
                <option value="" disabled>请选择区段</option>
                <option v-for="code in options.区段编码" :key="code" :value="code">{{ code }}</option>
              </select>
            </label>
            <label class="filter-item">
              <span>车站（与联锁设备台账一致）</span>
              <select v-model="batchMeta.车站">
                <option value="" disabled>请选择车站</option>
                <option v-for="name in options.车站" :key="name" :value="name">{{ name }}</option>
              </select>
            </label>
            <label class="filter-item">
              <span>批量生效日期</span>
              <input v-model="batchMeta.生效日期" type="date" />
            </label>
            <label class="add-files">
              <input ref="fileInput" type="file" multiple @change="onFilesPicked" hidden />
              <button class="btn" type="button" @click="pickFiles">选择文件（可多选）</button>
            </label>
          </div>

          <table class="data-table draft-table">
            <thead>
              <tr><th>#</th><th>文件</th><th>资料类型</th><th>资料名称</th><th>版本号</th><th>生效日期</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="(item, idx) in drafts" :key="item.key">
                <td>{{ idx + 1 }}</td>
                <td class="file-cell" :title="item.文件名">{{ item.文件名 }}<br /><small>{{ formatSize(item.大小) }}</small></td>
                <td>
                  <select v-model="item.资料类型">
                    <option v-for="t in options.资料类型" :key="t" :value="t">{{ t }}</option>
                  </select>
                </td>
                <td><input v-model="item.资料名称" placeholder="如：进站信号机布置图" /></td>
                <td><input v-model="item.版本号" placeholder="V1.0" class="version-input" /></td>
                <td><input v-model="item.生效日期" type="date" @input="item.dateTouched = true" /></td>
                <td><button class="link" type="button" @click="removeDraft(idx)">移除</button></td>
              </tr>
              <tr v-if="!drafts.length">
                <td colspan="7" class="empty-state">尚未选择文件；版本号请填 V1、v1.0、2.3.1 这类格式</td>
              </tr>
            </tbody>
          </table>

          <div class="modal-foot">
            <span v-if="wizardError" class="error-text">{{ wizardError }}</span>
            <span class="hint">图纸支持 pdf/dwg/dxf；竣工资料支持 pdf/doc/docx/xls/xlsx/zip/rar</span>
            <button class="btn ghost" type="button" @click="closeUpload">取消</button>
            <button class="btn primary" type="button" :disabled="!drafts.length || checking" @click="runPreflight">
              {{ checking ? '校验中…' : '先校验' }}
            </button>
          </div>
        </template>

        <!-- 第二步：校验结果 -->
        <template v-else>
          <div class="check-summary">
            <span class="tag latest">通过 {{ checkResult?.通过 ?? 0 }}</span>
            <span class="tag reject">驳回 {{ checkResult?.驳回 ?? 0 }}</span>
            <span class="tag dup">重复 {{ checkResult?.重复 ?? 0 }}</span>
            <span class="hint">驳回与重复条目不入库；确认后仅“通过”的 {{ checkResult?.通过 ?? 0 }} 份同批入库。</span>
          </div>

          <div v-if="(checkResult?.accepted ?? []).length" class="result-block">
            <h4>校验通过，待确认</h4>
            <ul>
              <li v-for="item in checkResult!.accepted" :key="item.index">
                <span class="tag latest">通过</span>{{ item.条目 }}（{{ formatSize(item.大小) }}）
              </li>
            </ul>
          </div>

          <div v-if="(checkResult?.rejected ?? []).length" class="result-block">
            <h4>以下条目缺少信息或不合规，不会入库</h4>
            <ul>
              <li v-for="item in checkResult!.rejected" :key="item.index">
                <span class="tag reject">驳回</span><strong>{{ item.条目 }}</strong>
                <ul class="reason-list"><li v-for="reason in item.原因" :key="reason">{{ reason }}</li></ul>
              </li>
            </ul>
          </div>

          <div v-if="(checkResult?.duplicates ?? []).length" class="result-block">
            <h4>重复资料，只保留已归档的一条</h4>
            <ul>
              <li v-for="item in checkResult!.duplicates" :key="item.index">
                <span class="tag dup">重复</span>{{ item.条目 }} — {{ item.原因 }}
              </li>
            </ul>
          </div>

          <div class="modal-foot">
            <span v-if="wizardError" class="error-text">{{ wizardError }}</span>
            <button class="btn ghost" type="button" @click="backToEdit">返回修改</button>
            <button class="btn" type="button" @click="discardBatch">放弃本批</button>
            <button
              class="btn primary"
              type="button"
              :disabled="!checkResult?.通过 || committing"
              :title="!checkResult?.通过 ? '没有可入库的通过条目' : ''"
              @click="commitBatch"
            >
              {{ committing ? '入库中…' : `确认入库 ${checkResult?.通过 ?? 0} 份` }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- 版本沿革 -->
    <div v-if="versionOpen" class="modal-mask" @click.self="versionOpen = false">
      <div class="modal">
        <h3>版本沿革：{{ versionTarget?.资料名称 }}</h3>
        <p class="page-desc">{{ versionTarget?.区段编码 }} · {{ versionTarget?.车站 }} · {{ versionTarget?.资料类型 }}</p>
        <table class="data-table">
          <thead><tr><th>版本号</th><th>生效日期</th><th>文件</th><th>上传人/时间</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="v in versionRows" :key="String(v.id)">
              <td>V{{ v.版本号 }}</td>
              <td>{{ v.生效日期 }}</td>
              <td>{{ v.文件名 }}</td>
              <td>{{ v.上传人 }}<br /><small>{{ v.uploaded_at }}</small></td>
              <td><span :class="v.is_latest ? 'tag latest' : 'tag history'">{{ v.is_latest ? '当前生效' : '历史版本' }}</span></td>
              <td class="row-actions">
                <button class="link" type="button" @click="openContent(v, false)">查看</button>
                <button
                  class="link"
                  type="button"
                  :disabled="!v.可下载"
                  :title="v.可下载 ? '下载文件' : '竣工资料旧版本只能查看，不能再下载'"
                  @click="openContent(v, true)"
                >
                  下载
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="modal-foot">
          <button class="btn" type="button" @click="versionOpen = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 按区段打包 -->
    <div v-if="packageOpen" class="modal-mask" @click.self="packageOpen = false">
      <div class="modal small">
        <h3>按区段打包取走</h3>
        <p class="page-desc">压缩包内含该区段每份资料的当前生效版本；历史版本不进包。</p>
        <label class="filter-item">
          <span>区段编码</span>
          <select v-model="packageSection">
            <option value="" disabled>请选择区段</option>
            <option v-for="code in options.区段编码" :key="code" :value="code">{{ code }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>车站（可选，不选则打包该区段全部车站）</span>
          <select v-model="packageStation">
            <option value="">全部车站</option>
            <option v-for="name in stationsOfSection" :key="name" :value="name">{{ name }}</option>
          </select>
        </label>
        <div class="modal-foot">
          <span v-if="wizardError" class="error-text">{{ wizardError }}</span>
          <button class="btn ghost" type="button" @click="packageOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="!packageSection" @click="downloadPackage">打包下载</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type CheckResult = {
  token: string
  总数: number
  通过: number
  驳回: number
  重复: number
  accepted: Array<Record<string, string | number>>
  rejected: Array<{ index: number; 条目: string; 原因: string[] }>
  duplicates: Array<{ index: number; 条目: string; 原因: string }>
}
type Draft = {
  key: number
  资料类型: string
  资料名称: string
  版本号: string
  生效日期: string
  dateTouched: boolean
  文件名: string
  大小: number
  文件内容: string
  上传人: string
}

const ENDPOINT = '/api/archive'
const columns = ['区段编码', '车站', '资料类型', '资料名称', '版本号', '生效日期', '文件名', '上传人', 'uploaded_at']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const showAll = ref(false)
const stats = ref([
  { label: '已归档资料（当前版本）', value: 0 },
  { label: '资料份数（含历史版本）', value: 0 },
  { label: '覆盖图纸/竣工资料', value: 0 },
  { label: '竣工资料历史版本', value: 0 },
])
const options = ref<{ 区段编码: string[]; 车站: string[]; 资料类型: string[] }>({ 区段编码: [], 车站: [], 资料类型: ['图纸', '竣工资料'] })
const filters = ref<Record<string, string>>({ 区段编码: '', 车站: '', 资料类型: '', keyword: '' })

const stationsOfSection = computed(() => {
  // 区段未选时不做臆测；区段本身的车站集合以全量台账车站为候选。
  return options.value.车站
})

function formatCell(row: Row, column: string): string {
  if (column === '版本号') return `V${row[column] ?? ''}`
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function formatSize(size: unknown): string {
  const n = Number(size ?? 0)
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)}MB`
  if (n >= 1024) return `${(n / 1024).toFixed(0)}KB`
  return `${n}B`
}

async function readError(response: Response): Promise<string> {
  try {
    const data = await response.json()
    return typeof data.detail === 'string' ? data.detail : '操作未生效，请稍后重试'
  } catch {
    return `接口返回 ${response.status}，操作未生效`
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  Object.entries(filters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  params.set('全部版本', showAll.value ? 'true' : 'false')
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error(await readError(response))
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '归档列表读取失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      const payload = await response.json()
      stats.value = payload.cards ?? stats.value
    }
  } catch {
    // 统计卡片不影响主列表，失败时保留零值
  }
}

async function reloadOptions() {
  try {
    const response = await request(`${ENDPOINT}/options`)
    if (response.ok) options.value = await response.json()
  } catch {
    // 下拉为空时用户仍可看到列表错误提示
  }
}

function resetFilters() {
  filters.value = { 区段编码: '', 车站: '', 资料类型: '', keyword: '' }
  showAll.value = false
  void reload()
}

// ---------- 文件直连：查看 / 下载（走浏览器原生请求，避开 JSON 封装） ----------

function openContent(row: Row, asDownload: boolean) {
  const action = asDownload ? 'download' : 'view'
  window.open(`${ENDPOINT}/${String(row.id)}/${action}`, asDownload ? '_self' : '_blank')
}
function viewFile(row: Row) {
  openContent(row, false)
}
function downloadFile(row: Row) {
  if (!row.可下载) return
  openContent(row, true)
}

// ---------- 上传向导 ----------

const uploadOpen = ref(false)
const step = ref<'edit' | 'check'>('edit')
const fileInput = ref<HTMLInputElement | null>(null)
const drafts = ref<Draft[]>([])
const draftSeq = ref(0)
const checking = ref(false)
const committing = ref(false)
const wizardError = ref('')
const checkResult = ref<CheckResult | null>(null)
const batchMeta = ref({ 区段编码: '', 车站: '', 生效日期: '' })

function openUpload() {
  uploadOpen.value = true
  step.value = 'edit'
  drafts.value = []
  checkResult.value = null
  wizardError.value = ''
  batchMeta.value = { 区段编码: '', 车站: '', 生效日期: '' }
}
function closeUpload() {
  uploadOpen.value = false
}
function pickFiles() {
  fileInput.value?.click()
}

function inferDraftName(filename: string): string {
  const dot = filename.lastIndexOf('.')
  return dot > 0 ? filename.slice(0, dot) : filename
}

function onFilesPicked(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  for (const file of files) {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result ?? '')
      const comma = result.indexOf(',')
      drafts.value.push({
        key: ++draftSeq.value,
        资料类型: '图纸',
        资料名称: inferDraftName(file.name),
        版本号: '',
        生效日期: batchMeta.value.生效日期,
        dateTouched: false,
        文件名: file.name,
        大小: file.size,
        文件内容: comma >= 0 ? result.slice(comma + 1) : result,
        上传人: '值班人员',
      })
    }
    reader.readAsDataURL(file)
  }
}

function removeDraft(index: number) {
  drafts.value.splice(index, 1)
}

// 批量生效日期改动时，同步给所有没有单独改过日期的条目。
watch(
  () => batchMeta.value.生效日期,
  (value) => {
    drafts.value.forEach((draft) => {
      if (!draft.dateTouched) draft.生效日期 = value
    })
  },
)

async function runPreflight() {
  wizardError.value = ''
  if (!drafts.value.length) return
  if (!batchMeta.value.区段编码 || !batchMeta.value.车站) {
    wizardError.value = '请先在上方选择区段编码与车站（需与设备台账一致）'
    return
  }
  // 区段与车站是整批口径，直接取批量选择值；生效日期允许每行单独调整。
  const items = drafts.value.map((draft) => ({
    资料类型: draft.资料类型,
    区段编码: batchMeta.value.区段编码,
    车站: batchMeta.value.车站,
    资料名称: draft.资料名称,
    版本号: draft.版本号,
    生效日期: draft.生效日期,
    文件名: draft.文件名,
    大小: draft.大小,
    文件内容: draft.文件内容,
    上传人: draft.上传人,
  }))
  checking.value = true
  try {
    const response = await request(`${ENDPOINT}/preflight`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    })
    if (!response.ok) throw new Error(await readError(response))
    checkResult.value = await response.json()
    step.value = 'check'
  } catch (error) {
    wizardError.value = error instanceof Error ? error.message : '校验请求失败'
  } finally {
    checking.value = false
  }
}

function backToEdit() {
  if (checkResult.value?.token) {
    void request(`${ENDPOINT}/discard`, {
      method: 'POST',
      body: JSON.stringify({ token: checkResult.value.token }),
    })
  }
  checkResult.value = null
  step.value = 'edit'
}

async function discardBatch() {
  if (checkResult.value?.token) {
    await request(`${ENDPOINT}/discard`, {
      method: 'POST',
      body: JSON.stringify({ token: checkResult.value.token }),
    })
  }
  uploadOpen.value = false
  wizardError.value = ''
}

async function commitBatch() {
  if (!checkResult.value?.token) return
  committing.value = true
  wizardError.value = ''
  try {
    const response = await request(`${ENDPOINT}/commit`, {
      method: 'POST',
      body: JSON.stringify({ token: checkResult.value.token }),
    })
    if (!response.ok) throw new Error(await readError(response))
    uploadOpen.value = false
    drafts.value = []
    checkResult.value = null
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    wizardError.value = error instanceof Error ? error.message : '确认入库失败，本批未生效'
  } finally {
    committing.value = false
  }
}

// ---------- 版本沿革 ----------

const versionOpen = ref(false)
const versionTarget = ref<Row | null>(null)
const versionRows = ref<Row[]>([])

async function openVersions(row: Row) {
  versionTarget.value = row
  versionRows.value = []
  versionOpen.value = true
  try {
    const response = await request(`${ENDPOINT}/versions/${String(row.group_id)}`)
    if (!response.ok) throw new Error(await readError(response))
    const payload = await response.json()
    versionRows.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本沿革读取失败'
  }
}

// ---------- 按区段打包 ----------

const packageOpen = ref(false)
const packageSection = ref('')
const packageStation = ref('')

function openPackage() {
  packageOpen.value = true
  packageSection.value = ''
  packageStation.value = ''
  wizardError.value = ''
}

function downloadPackage() {
  if (!packageSection.value) return
  const params = new URLSearchParams({ 区段编码: packageSection.value })
  if (packageStation.value) params.set('车站', packageStation.value)
  window.open(`${ENDPOINT}/package/zip?${params.toString()}`, '_self')
  packageOpen.value = false
}

onMounted(() => {
  void reloadOptions()
  void reload()
  void reloadStats()
})
</script>

<style scoped>
.page-actions {
  display: flex;
  gap: 8px;
}
.filter-item.checkbox {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 4px;
  padding-bottom: 2px;
}
.filter-item.checkbox span {
  font-size: 13px;
  color: #1f2937;
}
select,
.filter-item input,
.draft-table input,
.draft-table select {
  padding: 4px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
  min-width: 90px;
}
.tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  white-space: nowrap;
}
.tag.latest {
  background: #e7f0ff;
  color: #1f6feb;
}
.tag.history {
  background: #f1f5f9;
  color: #64748b;
}
.tag.reject {
  background: #fee4e2;
  color: #b42318;
  margin-right: 6px;
}
.tag.dup {
  background: #fef3c7;
  color: #92400e;
  margin-right: 6px;
}
.link:disabled {
  color: #94a3b8;
  cursor: not-allowed;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  z-index: 50;
}
.modal {
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  width: 720px;
  max-width: 100%;
  max-height: 86vh;
  overflow: auto;
}
.modal.wide {
  width: 1040px;
}
.modal.small {
  width: 480px;
}
.modal h3 {
  margin: 0 0 6px;
}
.modal h4 {
  margin: 12px 0 6px;
  font-size: 14px;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
}
.modal-foot .hint,
.hint {
  margin-right: auto;
  color: var(--muted);
  font-size: 12px;
}
.batch-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  margin: 10px 0;
}
.add-files {
  margin-left: auto;
}
.draft-table td {
  vertical-align: top;
}
.draft-table .file-cell {
  max-width: 180px;
  word-break: break-all;
}
.draft-table .version-input {
  width: 80px;
}
.check-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 10px 0;
}
.result-block ul {
  margin: 0;
  padding-left: 0;
  list-style: none;
  font-size: 13px;
}
.result-block li {
  margin-bottom: 6px;
}
.reason-list {
  margin: 4px 0 0 24px !important;
  list-style: disc !important;
  color: #b42318;
}
</style>
