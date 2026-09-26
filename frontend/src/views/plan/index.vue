<template>
  <section class="page" data-module="plan">
    <header class="page-head">
      <div>
        <h2>检修计划管理</h2>
        <p class="page-desc">天窗取消后整组顺延：计划日期整体后挪、关联任务同步，每次调整都留下操作人与批复意见。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记检修计划</button>
        <button class="btn" type="button" @click="exportRows">导出检修计划清单</button>
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
        <span>计划编号</span>
        <input v-model="filters.keyword" placeholder="按计划编号检索" />
      </label>
      <label class="filter-item">
        <span>计划状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
      <button class="btn primary" type="button" :disabled="!selectedIds.length" @click="openGroupPostpone">
        整组顺延{{ selectedIds.length ? `（已选 ${selectedIds.length} 条）` : '' }}
      </button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th class="col-check">
            <input
              type="checkbox"
              :checked="allSelected"
              :disabled="!selectableRows.length"
              @change="toggleSelectAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
          <th>调整记录</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-void': row.status === '已作废' }">
          <td class="col-check">
            <input
              type="checkbox"
              :value="Number(row.id)"
              v-model="selectedIds"
              :disabled="row.status === '已作废'"
            />
          </td>
          <td v-for="column in columns" :key="column">
            <template v-if="column === '计划状态'">
              <span class="status-tag" :data-status="row.status">{{ row.status }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <template v-if="actionsFor(row.status).length">
              <button
                v-for="action in actionsFor(row.status)"
                :key="action"
                class="link"
                type="button"
                @click="openStatusAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <button v-if="row.status !== '已作废'" class="link" type="button" @click="openRowPostpone(row)">顺延</button>
            <span v-else class="muted-text">—</span>
          </td>
          <td>
            <button class="link" type="button" @click="openHistory(row)">
              调整记录{{ historyCount(row) ? `（${historyCount(row)}）` : '' }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无检修计划数据，可先登记检修计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条检修计划记录</span>
      <span v-if="feedback" class="success-text">{{ feedback }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 顺延天数 / 批复意见 -->
    <div v-if="postponeForm.open" class="modal-mask" @click.self="closePostponeForm">
      <div class="modal">
        <h3 class="modal-title">{{ postponeForm.planId ? '单条计划顺延' : '整组计划顺延' }}</h3>
        <div class="modal-tip">
          当前操作人：<strong>{{ session.operator }}</strong
          >；顺延后计划日期与关联检修任务时间将整体后移。
        </div>
        <label class="form-item">
          <span>顺延天数（天）</span>
          <input v-model.number="postponeForm.days" type="number" min="1" step="1" placeholder="例如 3" />
        </label>
        <label class="form-item">
          <span>批复意见 / 调整说明</span>
          <textarea v-model="postponeForm.opinion" rows="3" placeholder="说明顺延原因，如：天窗取消，计划顺延"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closePostponeForm">取消</button>
          <button class="btn primary" type="button" @click="requestPreview">生成预览</button>
        </div>
      </div>
    </div>

    <!-- 顺延预览 -->
    <div v-if="preview" class="modal-mask" @click.self="closePreview">
      <div class="modal modal-wide">
        <h3 class="modal-title">顺延预览（整体后移 {{ preview.days }} 天）</h3>
        <p class="modal-tip">
          共 {{ preview.apply_count }} 条计划将顺延，
          <span :class="preview.skip_count ? 'warn-text' : ''">{{ preview.skip_count }} 条已作废自动跳过</span>
          ；确认后才会生效。
        </p>
        <table class="data-table preview-table">
          <thead>
            <tr>
              <th>计划编号</th>
              <th>检修对象</th>
              <th>当前状态</th>
              <th>原计划日期</th>
              <th>顺延后日期</th>
              <th>关联任务同步</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in preview.items" :key="String(item.id)">
              <td>{{ item['计划编号'] }}</td>
              <td>{{ item['检修对象'] ?? '—' }}</td>
              <td><span class="status-tag" :data-status="item.status">{{ item.status }}</span></td>
              <td>{{ item.old_计划日期 || '—' }}</td>
              <td>{{ item.new_计划日期 || '—' }}</td>
              <td>
                <span v-if="!item.tasks.length" class="muted-text">无关联任务</span>
                <div v-for="task in item.tasks" :key="String(task.task_id)">
                  {{ task['任务编号'] }}：{{ task.old_开始时间 || '—' }} → {{ task.new_开始时间 || '—' }}
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="preview.skipped.length" class="skip-box">
          <strong>已跳过：</strong>
          <span v-for="(skip, index) in preview.skipped" :key="String(skip.id)">
            {{ skip['计划编号'] }}（{{ skip.reason }}）<span v-if="index < preview.skipped.length - 1">；</span>
          </span>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="backToForm">返回修改</button>
          <button class="btn primary" type="button" @click="confirmPostpone">确认顺延</button>
        </div>
      </div>
    </div>

    <!-- 状态流转：批复意见 -->
    <div v-if="actionForm.open" class="modal-mask" @click.self="closeStatusAction">
      <div class="modal">
        <h3 class="modal-title">{{ actionForm.action }}</h3>
        <div class="modal-tip">
          计划 {{ actionForm.code }}：{{ actionForm.fromStatus }} → {{ actionForm.toStatus }}，操作人
          <strong>{{ session.operator }}</strong>。状态只允许往前推进，提交后不可回退。
        </div>
        <label class="form-item">
          <span>批复意见</span>
          <textarea v-model="actionForm.opinion" rows="3" placeholder="请填写批复意见"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeStatusAction">取消</button>
          <button class="btn primary" type="button" @click="submitStatusAction">确认提交</button>
        </div>
      </div>
    </div>

    <!-- 调整记录 -->
    <div v-if="historyTarget" class="modal-mask" @click.self="historyTarget = null">
      <div class="modal modal-wide">
        <h3 class="modal-title">调整记录 · {{ historyTarget['计划编号'] }}</h3>
        <div v-if="!historyList.length" class="empty-state">暂无调整记录</div>
        <ul v-else class="history-list">
          <li v-for="(record, index) in historyList" :key="index" class="history-item">
            <div class="history-head">
              <span class="history-type" :data-type="record.type">{{ record.type }}</span>
              <strong>{{ record.action }}</strong>
              <span v-if="record.batch_no" class="muted-text">批次 {{ record.batch_no }}</span>
            </div>
            <div v-if="record.type === '状态流转'">
              {{ record.from_status }} → {{ record.to_status }}
            </div>
            <div v-else>
              计划日期 {{ record.from_date || '—' }} → {{ record.to_date || '—' }}（顺延 {{ record.days }} 天）
              <div v-if="record.synced_tasks?.length" class="muted-text">
                关联任务同步：{{ record.synced_tasks.join('、') }}
              </div>
            </div>
            <div class="history-foot muted-text">
              操作人：{{ record.operator }} ｜ 批复意见：{{ record.opinion }} ｜ {{ record.at }}
            </div>
          </li>
        </ul>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="historyTarget = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | boolean | null>

interface HistoryRecord {
  type: string
  action: string
  from_status?: string
  to_status?: string
  days?: number
  from_date?: string
  to_date?: string
  synced_tasks?: string[]
  batch_no?: string
  operator: string
  opinion: string
  at: string
}

interface TaskChange {
  task_id: number
  任务编号: string
  old_开始时间: string
  new_开始时间: string
  old_完成时间?: string
  new_完成时间?: string
  changed: boolean
}

interface PostponeItem {
  id: number
  计划编号: string
  检修对象: string | null
  status: string
  old_计划日期: string
  new_计划日期: string
  date_shiftable: boolean
  tasks: TaskChange[]
}

interface PostponePreview {
  days: number
  batch_no: string | null
  items: PostponeItem[]
  skipped: { id: number; 计划编号: string; reason: string }[]
  apply_count: number
  skip_count: number
}

interface ActionEnvelope {
  ok: boolean
  message: string
  entry?: Row | null
}

const ENDPOINT = '/api/plan'
const columns = ['计划编号', '检修类型', '检修对象', '计划日期', '检修周期', '作业班组', '计划工时', '计划状态']
const statuses = ['待审批', '已批复', '执行中', '已作废']
// 每个状态下只保留能往前推进一档的动作；执行中、已作废没有可执行动作。
const NEXT_ACTIONS: Record<string, string[]> = {
  待审批: ['提交审批', '作废计划'],
  已批复: ['确认执行', '作废计划'],
  执行中: [],
  已作废: [],
}
const ACTION_TARGETS: Record<string, string> = {
  提交审批: '已批复',
  确认执行: '执行中',
  作废计划: '已作废',
}
const DEFAULT_STATS = [
  { label: '待审批计划', value: 0 },
  { label: '已批复计划', value: 0 },
  { label: '执行中计划', value: 0 },
  { label: '已作废计划', value: 0 },
]

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const feedback = ref('')
const filters = ref<{ keyword: string; status: string }>({ keyword: '', status: '' })
const selectedIds = ref<number[]>([])

const stats = ref(DEFAULT_STATS.map((item) => ({ ...item })))

const selectableRows = computed(() => rows.value.filter((row) => row.status !== '已作废'))
const allSelected = computed(
  () => selectableRows.value.length > 0
    && selectableRows.value.every((row) => selectedIds.value.includes(Number(row.id))),
)

const postponeForm = ref({
  open: false,
  planId: 0 as number,
  days: 3,
  opinion: '',
})
const preview = ref<PostponePreview | null>(null)
const pendingOpinion = ref('')

const actionForm = ref({
  open: false,
  action: '',
  toStatus: '',
  fromStatus: '',
  code: '',
  entryId: 0,
  opinion: '',
})
const historyTarget = ref<Row | null>(null)

function actionsFor(status: string | number | boolean | null | undefined): string[] {
  return NEXT_ACTIONS[String(status)] ?? []
}

function historyCount(row: Row): number {
  const history = row.history as unknown as HistoryRecord[] | undefined
  return Array.isArray(history) ? history.length : 0
}

function toggleSelectAll() {
  if (allSelected.value) {
    const selectable = new Set(selectableRows.value.map((row) => Number(row.id)))
    selectedIds.value = selectedIds.value.filter((id) => !selectable.has(id))
  } else {
    selectedIds.value = selectableRows.value.map((row) => Number(row.id))
  }
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '检修计划登记入口尚未接入审批流'
}

// ---------------------------------------------------------------- 状态流转

function openStatusAction(action: string, row: Row) {
  errorMessage.value = ''
  actionForm.value = {
    open: true,
    action,
    toStatus: ACTION_TARGETS[action],
    fromStatus: String(row.status),
    code: String(row['计划编号']),
    entryId: Number(row.id),
    opinion: '',
  }
}

function closeStatusAction() {
  actionForm.value.open = false
}

async function submitStatusAction() {
  const form = actionForm.value
  errorMessage.value = ''
  feedback.value = ''
  if (!form.opinion.trim()) {
    errorMessage.value = '请填写批复意见后再提交'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${form.entryId}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: { action: form.action, operator: session.operator, opinion: form.opinion },
      }),
    })
    const result = (await response.json()) as ActionEnvelope
    if (!response.ok || !result.ok) {
      throw new Error(result.message || '检修计划动作未生效，请稍后重试')
    }
    feedback.value = result.message
    form.open = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修计划操作失败'
  }
}

// ---------------------------------------------------------------- 顺延链路

function openGroupPostpone() {
  errorMessage.value = ''
  feedback.value = ''
  if (!selectedIds.value.length) {
    errorMessage.value = '请先勾选要顺延的检修计划'
    return
  }
  postponeForm.value = { open: true, planId: 0, days: 3, opinion: '' }
}

function openRowPostpone(row: Row) {
  errorMessage.value = ''
  feedback.value = ''
  selectedIds.value = [Number(row.id)]
  postponeForm.value = { open: true, planId: Number(row.id), days: 3, opinion: '' }
}

function closePostponeForm() {
  postponeForm.value.open = false
}

function targetIds(): number[] {
  return postponeForm.value.planId ? [postponeForm.value.planId] : selectedIds.value
}

async function requestPreview() {
  errorMessage.value = ''
  const days = Number(postponeForm.value.days)
  if (!Number.isInteger(days) || days <= 0) {
    errorMessage.value = '顺延天数必须是大于 0 的整数'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/postpone/preview`, {
      method: 'POST',
      body: JSON.stringify({ ids: targetIds(), days }),
    })
    const result = (await response.json()) as ActionEnvelope
    if (!response.ok || !result.ok || !result.entry) {
      throw new Error(result.message || '顺延预览生成失败')
    }
    pendingOpinion.value = postponeForm.value.opinion
    preview.value = result.entry as unknown as PostponePreview
    postponeForm.value.open = false
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '顺延预览生成失败'
  }
}

function backToForm() {
  preview.value = null
  postponeForm.value.opinion = pendingOpinion.value
  postponeForm.value.open = true
}

function closePreview() {
  preview.value = null
}

async function confirmPostpone() {
  if (!preview.value) {
    return
  }
  errorMessage.value = ''
  feedback.value = ''
  if (!pendingOpinion.value.trim()) {
    errorMessage.value = '请填写批复意见后再确认顺延'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/postpone/confirm`, {
      method: 'POST',
      body: JSON.stringify({
        ids: targetIds(),
        days: preview.value.days,
        operator: session.operator,
        opinion: pendingOpinion.value,
      }),
    })
    const result = (await response.json()) as ActionEnvelope
    if (!response.ok || !result.ok) {
      throw new Error(result.message || '顺延未生效，请稍后重试')
    }
    feedback.value = result.message
    preview.value = null
    selectedIds.value = []
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '顺延确认失败'
  }
}

// ---------------------------------------------------------------- 调整记录

const historyList = computed<HistoryRecord[]>(() => {
  if (!historyTarget.value) {
    return []
  }
  const history = historyTarget.value.history as unknown as HistoryRecord[] | undefined
  return Array.isArray(history) ? [...history].reverse() : []
})

function openHistory(row: Row) {
  historyTarget.value = row
}

// ---------------------------------------------------------------- 列表加载

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/export`)
    if (!response.ok) {
      return
    }
    const payload = (await response.json()) as { items?: Row[] }
    const all = payload.items ?? []
    const counts = new Map(statuses.map((status) => [status, 0]))
    all.forEach((row) => {
      const status = String(row.status)
      if (counts.has(status)) {
        counts.set(status, (counts.get(status) ?? 0) + 1)
      }
    })
    stats.value = statuses.map((status) => ({ label: `${status}计划`, value: counts.get(status) ?? 0 }))
  } catch {
    // 统计只是辅助信息，拉取失败不阻断列表操作。
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value.keyword.trim()) {
    params.set('keyword', filters.value.keyword.trim())
  }
  if (filters.value.status) {
    params.set('status', filters.value.status)
  }
  const query = params.toString()
  try {
    const response = await request(query ? `${ENDPOINT}?${query}` : ENDPOINT)
    if (!response.ok) {
      throw new Error('检修计划列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 筛选后清掉已不在当前页的选中项，返回列表也不会回退状态。
    const visibleIds = new Set(rows.value.map((row) => Number(row.id)))
    selectedIds.value = selectedIds.value.filter((id) => visibleIds.has(id))
    await loadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修计划列表读取失败'
  }
}

void onMounted(reload)
</script>

<style scoped>
.col-check {
  width: 36px;
  text-align: center;
}
.muted-text {
  color: var(--muted);
}
.warn-text {
  color: #b54708;
}
.success-text {
  color: #067647;
}
.row-void td {
  color: var(--muted);
}
.status-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  border: 1px solid var(--border);
  background: #f1f5f9;
}
.status-tag[data-status='待审批'] {
  background: #eff8ff;
  border-color: #b2ddff;
  color: #175cd3;
}
.status-tag[data-status='已批复'] {
  background: #f0fdf4;
  border-color: #abefc6;
  color: #067647;
}
.status-tag[data-status='执行中'] {
  background: #fffaeb;
  border-color: #fedf89;
  color: #b54708;
}
.status-tag[data-status='已作废'] {
  background: #fef3f2;
  border-color: #fecdca;
  color: #b42318;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  width: 480px;
  max-height: 86vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.2);
}
.modal-wide {
  width: 760px;
}
.modal-title {
  margin: 0 0 8px;
  font-size: 16px;
}
.modal-tip {
  font-size: 13px;
  color: var(--muted);
  margin: 0 0 12px;
}
.form-item {
  display: block;
  margin-bottom: 12px;
}
.form-item span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.form-item input,
.form-item textarea,
.filter-item select {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  font-family: inherit;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
.preview-table {
  margin-top: 4px;
}
.skip-box {
  margin-top: 10px;
  padding: 8px 10px;
  border: 1px solid #fedf89;
  background: #fffaeb;
  border-radius: 6px;
  font-size: 13px;
}
.history-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.history-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.history-head {
  display: flex;
  gap: 8px;
  align-items: center;
}
.history-type {
  padding: 0 8px;
  border-radius: 10px;
  font-size: 12px;
  background: #eff8ff;
  color: #175cd3;
}
.history-type[data-type='顺延调整'] {
  background: #fffaeb;
  color: #b54708;
}
.history-foot {
  font-size: 12px;
}
</style>
