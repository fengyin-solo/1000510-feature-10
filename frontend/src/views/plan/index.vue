<template>
  <section class="page" data-module="plan">
    <header class="page-head">
      <div>
        <h2>检修计划管理</h2>
        <p class="page-desc">
          计划按待审批 → 已批复 → 执行中 → 已作废逐档流转；天窗取消可整组顺延，
          顺延先预览再确认，日期整体后移并同步关联检修任务明细，每次调整都留操作人与批复意见。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" :disabled="!selectedIds.size" @click="openPostpone()">
          整组顺延{{ selectedIds.size ? `（已选 ${selectedIds.size} 条）` : '' }}
        </button>
        <button class="btn" type="button" @click="exportRows">导出检修计划清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statsCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>计划编号</span>
        <input v-model="keyword" placeholder="按计划编号检索" />
      </label>
      <label class="filter-item">
        <span>计划状态</span>
        <select v-model="statusFilter">
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
          <th class="col-check">
            <input
              type="checkbox"
              :checked="allSelected"
              :disabled="!selectableRows.length"
              @change="toggleSelectAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>计划状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="col-check">
            <input
              v-if="row.status !== '已作废'"
              type="checkbox"
              :checked="isSelected(row)"
              @change="toggleSelect(row)"
            />
            <span v-else class="check-disabled" title="已作废计划不参与顺延">—</span>
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span class="status-tag" :class="`status-${statusIndex(row.status)}`">{{ row.status }}</span>
          </td>
          <td class="row-actions">
            <template v-if="availableActions(row).length">
              <button
                v-for="action in availableActions(row)"
                :key="action"
                class="link"
                :class="{ danger: action === '作废计划' }"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
              <button class="link" type="button" @click="openPostpone([row])">顺延</button>
            </template>
            <button class="link" type="button" @click="openHistories(row)">调整记录</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无检修计划数据，可先登记检修计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条检修计划记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 顺延链路：先填天数与批复意见，再预览，确认后才落库 -->
    <div v-if="postponeVisible" class="modal-mask" @click.self="closePostpone">
      <div class="modal">
        <header class="modal-head">
          <h3>检修计划整组顺延</h3>
          <button class="link" type="button" @click="closePostpone">关闭</button>
        </header>

        <div class="modal-body">
          <div v-if="!preview" class="postpone-form">
            <p class="modal-tip">
              已选 {{ postponeIds.length }} 条计划；已作废的计划会自动跳过，不影响同组其他计划。
              顺延后计划日期整体后移，关联检修任务的开始/完成时间同步后移。
            </p>
            <label class="filter-item">
              <span>顺延天数（天）</span>
              <input v-model.number="postponeDays" type="number" min="1" step="1" placeholder="例如 3" />
            </label>
            <label class="filter-item">
              <span>批复意见</span>
              <textarea
                v-model="postponeComment"
                rows="3"
                placeholder="如：天窗取消，计划顺延三日"
              ></textarea>
            </label>
            <p v-if="modalError" class="error-text">{{ modalError }}</p>
          </div>

          <template v-else>
            <p class="modal-tip">
              预览：整体后移 {{ preview.days }} 天，以下 {{ preview.plans.length }} 条计划参与顺延，
              其关联检修任务明细同步后移。
            </p>
            <table class="data-table preview-table">
              <thead>
                <tr>
                  <th>计划编号</th>
                  <th>检修对象</th>
                  <th>当前状态</th>
                  <th>计划日期</th>
                  <th>顺延后日期</th>
                  <th>关联明细同步</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="plan in preview.plans" :key="String(plan.id)">
                  <td>{{ plan.计划编号 ?? '—' }}</td>
                  <td>{{ plan.检修对象 ?? '—' }}</td>
                  <td>{{ plan.status }}</td>
                  <td>{{ plan.date_from || '—' }}</td>
                  <td>
                    <span v-if="plan.date_shifted" class="shift-arrow">
                      {{ plan.date_from }} → <strong>{{ plan.date_to }}</strong>
                    </span>
                    <span v-else class="muted-text">日期格式无法识别，保持原值</span>
                  </td>
                  <td>
                    <span v-if="!plan.linked_details.length" class="muted-text">无关联检修任务</span>
                    <ul v-else class="detail-list">
                      <li v-for="detail in plan.linked_details" :key="String(detail.id)">
                        {{ detail.任务编号 }}：
                        {{ detail.shifts['开始时间'].from || '—' }}
                        →
                        <template v-if="detail.shifts['开始时间'].shifted">
                          {{ detail.shifts['开始时间'].to }}
                        </template>
                        <template v-else>原值</template>
                      </li>
                    </ul>
                  </td>
                </tr>
              </tbody>
            </table>

            <div v-if="preview.excluded.length" class="excluded-box">
              <strong>以下 {{ preview.excluded.length }} 条不参与顺延，不影响其他计划：</strong>
              <ul class="detail-list">
                <li v-for="item in preview.excluded" :key="String(item.id)">
                  {{ item.计划编号 ?? `#${item.id}` }}：{{ item.reason }}
                </li>
              </ul>
            </div>

            <div v-if="applied" class="applied-box">
              <strong>{{ applied.message }}</strong>
              <p class="muted-text">操作人：{{ applied.result.operator }} · 批复意见：{{ applied.result.comment }}</p>
            </div>

            <p v-if="modalError" class="error-text">{{ modalError }}</p>
          </template>
        </div>

        <footer class="modal-foot">
          <button class="btn ghost" type="button" @click="closePostpone">
            {{ applied ? '完成' : '取消' }}
          </button>
          <template v-if="!preview">
            <button class="btn primary" type="button" @click="fetchPreview">生成顺延预览</button>
          </template>
          <template v-else-if="!applied">
            <button class="btn" type="button" @click="backToPostponeForm">返回修改</button>
            <button class="btn primary" type="button" @click="confirmPostpone">确认顺延</button>
          </template>
        </footer>
      </div>
    </div>

    <!-- 调整记录留痕 -->
    <div v-if="historiesVisible" class="modal-mask" @click.self="closeHistories">
      <div class="modal modal-narrow">
        <header class="modal-head">
          <h3>调整记录 · {{ historyPlan?.计划编号 }}</h3>
          <button class="link" type="button" @click="closeHistories">关闭</button>
        </header>
        <div class="modal-body">
          <ul v-if="histories.length" class="history-list">
            <li v-for="item in histories" :key="item.seq" class="history-item">
              <div class="history-line">
                <span class="history-seq">第 {{ item.seq }} 次</span>
                <strong>{{ item.action }}</strong>
                <span class="muted-text">{{ item.operated_at }}</span>
              </div>
              <div class="history-line">
                <span class="status-tag" :class="`status-${statusIndex(item.from_status)}`">{{ item.from_status || '—' }}</span>
                <span class="shift-arrow">→</span>
                <span class="status-tag" :class="`status-${statusIndex(item.to_status)}`">{{ item.to_status || '—' }}</span>
              </div>
              <div class="history-line muted-text">
                操作人：{{ item.operator }}
                <template v-if="item.days">· 后移 {{ item.days }} 天（{{ item.date_from }} → {{ item.date_to }}，同步明细 {{ item.linked_count }} 条）</template>
              </div>
              <div class="history-line">批复意见：{{ item.comment }}</div>
            </li>
          </ul>
          <p v-else class="empty-state">该计划暂无调整记录</p>
          <p v-if="modalError" class="error-text">{{ modalError }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null>

interface DateShift {
  from: string | null
  to: string
  shifted: boolean
}
interface LinkedDetail {
  id: number
  任务编号: string | null
  shifts: Record<string, DateShift>
  shifted: boolean
}
interface PreviewPlan {
  id: number
  计划编号: string | null
  检修对象: string | null
  status: string
  date_from: string
  date_to: string
  date_shifted: boolean
  linked_details: LinkedDetail[]
}
interface ExcludedPlan {
  id: number
  计划编号: string | null
  reason: string
}
interface Preview {
  days: number
  plans: PreviewPlan[]
  excluded: ExcludedPlan[]
}
interface History {
  seq: number
  action: string
  from_status: string
  to_status: string
  operator: string
  comment: string
  operated_at: string
  days?: number
  date_from?: string
  date_to?: string
  linked_count?: number
}
interface ApiResult {
  ok: boolean
  message: string
  entry?: Record<string, unknown> | null
}
interface AppliedResult {
  message: string
  result: {
    operator: string
    comment: string
  }
}

const ENDPOINT = '/api/plan'
const columns = ['计划编号', '检修类型', '检修对象', '计划日期', '检修周期', '作业班组', '计划工时']
const statuses = ['待审批', '已批复', '执行中', '已作废']
const session = useSessionStore()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const selectedIds = ref<Set<number>>(new Set())

// 顺延弹窗状态
const postponeVisible = ref(false)
const postponeIds = ref<number[]>([])
const postponeDays = ref<number | null>(3)
const postponeComment = ref('')
const preview = ref<Preview | null>(null)
const applied = ref<AppliedResult | null>(null)
const modalError = ref('')

// 留痕弹窗状态
const historiesVisible = ref(false)
const histories = ref<History[]>([])
const historyPlan = ref<Row | null>(null)

const selectableRows = computed(() => rows.value.filter((row) => row.status !== '已作废'))
const allSelected = computed(
  () => selectableRows.value.length > 0
    && selectableRows.value.every((row) => selectedIds.value.has(Number(row.id))),
)

const statsCards = computed(() => [
  { label: '待审批计划', value: rows.value.filter((row) => row.status === '待审批').length },
  { label: '执行中计划', value: rows.value.filter((row) => row.status === '执行中').length },
  { label: '已作废计划', value: rows.value.filter((row) => row.status === '已作废').length },
])

function statusIndex(status: string | number | null | undefined): number {
  const index = statuses.indexOf(String(status ?? ''))
  return index < 0 ? 0 : index
}

/** 状态只能向前推进：按当前档位只放行下一档动作，作废在任意未作废档位都可用。 */
function availableActions(row: Row): string[] {
  switch (row.status) {
    case '待审批':
      return ['提交审批', '作废计划']
    case '已批复':
      return ['确认执行', '作废计划']
    case '执行中':
      return ['作废计划']
    default:
      return []
  }
}

function isSelected(row: Row): boolean {
  return selectedIds.value.has(Number(row.id))
}

function toggleSelect(row: Row) {
  const next = new Set(selectedIds.value)
  if (next.has(Number(row.id))) {
    next.delete(Number(row.id))
  } else {
    next.add(Number(row.id))
  }
  selectedIds.value = next
}

function toggleSelectAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  selectedIds.value = checked
    ? new Set(selectableRows.value.map((row) => Number(row.id)))
    : new Set()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function callApi(path: string, body: unknown): Promise<ApiResult | null> {
  try {
    const response = await request(path, {
      method: 'POST',
      body: JSON.stringify(body),
    })
    return (await response.json()) as ApiResult
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : '接口请求失败',
    }
  }
}

/** 老动作照旧：确认执行等保持一键完成；作废不可逆，先确认一次。意见与操作人照常留痕。 */
async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  if (action === '作废计划' && !window.confirm(`确定作废 ${row.计划编号} 吗？作废后不能改回待审批等任何档位。`)) {
    return
  }
  const result = await callApi(`${ENDPOINT}/${row.id}/actions`, {
    action,
    operator: session.operator,
  })
  if (!result || !result.ok) {
    errorMessage.value = result?.message ?? '检修计划动作未生效'
    return
  }
  selectedIds.value.delete(Number(row.id))
  await reload()
}

function openPostpone(plans?: Row[]) {
  const source = plans
    ? plans.filter((row) => row.status !== '已作废').map((row) => Number(row.id))
    : [...selectedIds.value]
  if (!source.length) {
    errorMessage.value = '请先勾选需要顺延的计划（已作废计划不参与顺延）'
    return
  }
  postponeIds.value = source
  postponeDays.value = 3
  postponeComment.value = ''
  preview.value = null
  applied.value = null
  modalError.value = ''
  postponeVisible.value = true
}

function backToPostponeForm() {
  preview.value = null
  modalError.value = ''
}

function closePostpone() {
  postponeVisible.value = false
  void reload()
}

async function fetchPreview() {
  modalError.value = ''
  const days = Number(postponeDays.value)
  if (!Number.isInteger(days) || days < 1) {
    modalError.value = '顺延天数必须是大于 0 的整数'
    return
  }
  const result = await callApi(`${ENDPOINT}/postpone/preview`, {
    plan_ids: postponeIds.value,
    days,
  })
  if (!result || !result.ok) {
    modalError.value = result?.message ?? '顺延预览生成失败'
    return
  }
  preview.value = result.entry as unknown as Preview
}

async function confirmPostpone() {
  modalError.value = ''
  if (!postponeComment.value.trim()) {
    modalError.value = '请填写批复意见后再确认顺延'
    return
  }
  const result = await callApi(`${ENDPOINT}/postpone/apply`, {
    plan_ids: postponeIds.value,
    days: Number(postponeDays.value),
    comment: postponeComment.value.trim(),
    operator: session.operator,
  })
  if (!result || !result.ok) {
    modalError.value = result?.message ?? '顺延未生效'
    return
  }
  applied.value = {
    message: result.message,
    result: result.entry as unknown as AppliedResult['result'],
  }
  selectedIds.value = new Set()
  await reload()
}

async function openHistories(row: Row) {
  historyPlan.value = row
  histories.value = []
  modalError.value = ''
  historiesVisible.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/histories`)
    const result = (await response.json()) as ApiResult
    if (!result.ok) {
      modalError.value = result.message
      return
    }
    histories.value = ((result.entry as { histories?: History[] })?.histories) ?? []
  } catch (error) {
    modalError.value = error instanceof Error ? error.message : '调整记录读取失败'
  }
}

function closeHistories() {
  historiesVisible.value = false
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) {
    query.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  query.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('检修计划列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    // 返回列表后只保留仍存在且未作废的勾选项，状态一律以后端返回为准，不回退。
    const visibleIds = new Set(rows.value.map((row) => Number(row.id)))
    selectedIds.value = new Set(
      [...selectedIds.value].filter((id) => visibleIds.has(id)),
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检修计划列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.col-check {
  width: 40px;
  text-align: center;
}
.check-disabled {
  color: var(--muted);
}
.page-actions .btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.status-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  background: #eef2ff;
  color: #3730a3;
}
.status-1 {
  background: #ecfdf3;
  color: #027a48;
}
.status-2 {
  background: #fff7ed;
  color: #c2410c;
}
.status-3 {
  background: #f2f4f7;
  color: #667085;
}
.link.danger {
  color: #b42318;
}
.muted-text {
  color: var(--muted);
}
.shift-arrow {
  color: var(--brand);
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  width: 860px;
  max-width: calc(100vw - 48px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
}
.modal-narrow {
  width: 560px;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}
.modal-head h3 {
  margin: 0;
  font-size: 15px;
}
.modal-body {
  padding: 14px 18px;
  overflow: auto;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px;
  border-top: 1px solid var(--border);
}
.modal-tip {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--muted);
}
.postpone-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.postpone-form textarea,
.postpone-form input,
.filter-bar select {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  font-family: inherit;
}
.preview-table th,
.preview-table td {
  font-size: 12px;
}
.detail-list {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
}
.excluded-box {
  margin-top: 12px;
  border: 1px dashed #f0a8a0;
  background: #fef3f2;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
}
.applied-box {
  margin-top: 12px;
  border: 1px solid #abefc6;
  background: #ecfdf3;
  border-radius: 8px;
  padding: 8px 12px;
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
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
}
.history-line {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.history-seq {
  background: #eef2ff;
  color: #3730a3;
  border-radius: 10px;
  padding: 0 8px;
  font-size: 12px;
}
</style>
