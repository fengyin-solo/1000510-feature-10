"""检修计划业务规则：状态流转、顺延调整、留痕与筛选口径都收在这里。

约束（业务侧确认）：
- 状态只能顺着「待审批 → 已批复 → 执行中 → 已作废」往前推进，不允许回到上一档；
  作废是终止档，作废后不可再改回任何状态。
- 每次状态切换、每次顺延都要记下操作人、批复意见与调整前后的值。
- 顺延把计划日期整体往后挪，并同步把关联检修任务（按计划编号关联）的时间一并后移。
- 整组顺延前先出预览；已作废的计划直接跳过，不能因为一条作废而拖住整组。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.store import store

MODULE = "plan"
TASK_MODULE = "task"
REQUIRED_FIELDS = ["计划编号", "检修类型", "检修对象"]
STATUS_ORDER = ["待审批", "已批复", "执行中", "已作废"]
VOID_STATUS = "已作废"
# 每个动作只能把当前状态推进到紧挨着的下一档，杜绝跳档与回退。
ACTION_RULES: dict[str, str] = {
    "提交审批": "已批复",
    "确认执行": "执行中",
    "作废计划": "已作废",
}
# 动作只在这些当前状态下可用：作废只能从审批前/批复后发起，执行中不可作废。
ACTION_FROM_STATUSES: dict[str, tuple[str, ...]] = {
    "提交审批": ("待审批",),
    "确认执行": ("已批复",),
    "作废计划": ("待审批", "已批复"),
}
DATE_FIELD = "计划日期"
TASK_DATE_FIELDS = ("开始时间", "完成时间")
HISTORY_KEY = "history"
DEFAULT_OPERATOR = "值班管理员"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_date(value: Any) -> date | None:
    """把 'YYYY-MM-DD' 或带时间的字符串解析成日期，解析不了就返回 None（不抛异常）。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _shift_date(value: Any, days: int) -> str | None:
    parsed = _parse_date(value)
    if parsed is None:
        return None
    return (parsed + timedelta(days=days)).isoformat()


def _append_history(entry: dict[str, Any], record: dict[str, Any]) -> None:
    entry.setdefault(HISTORY_KEY, []).append(record)


class PlanService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("计划编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 登记时允许一并带上计划日期等业务字段，便于后续顺延与关联。
        for field in ("检修类型", "检修对象", "计划日期", "检修周期", "作业班组", "计划工时"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry[HISTORY_KEY] = []
        rows.append(entry)
        return entry, []

    # ------------------------------------------------------------------ 状态流转

    def available_actions(self, status: str) -> list[str]:
        """返回某状态下还能往前推进的动作（作废档为空，执行中无后续动作）。"""
        return [
            action
            for action, allowed in ACTION_FROM_STATUSES.items()
            if status in allowed
        ]

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str | None = None,
        opinion: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检修计划 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于检修计划可执行范围"
        opinion = str(opinion or "").strip()
        if not opinion:
            return None, "请填写批复意见后再提交"

        current = entry.get("status")
        if current == VOID_STATUS:
            return None, "已作废的计划不能改回待审批或继续流转"
        if current not in ACTION_FROM_STATUSES.get(action, ()):
            return None, f"计划当前为「{current}」，不能执行「{action}」，状态只允许往前推进"

        target = ACTION_RULES[action]
        # 双保险：即便规则表配错，也不允许档位回退。
        if STATUS_ORDER.index(target) <= STATUS_ORDER.index(current):
            return None, "状态切换只允许往前推进，不能回到上一档"

        _append_history(entry, {
            "type": "状态流转",
            "action": action,
            "from_status": current,
            "to_status": target,
            "operator": operator or DEFAULT_OPERATOR,
            "opinion": opinion,
            "at": _now(),
        })
        entry["status"] = target
        entry["pending"] = target != VOID_STATUS
        entry["abnormal"] = target == VOID_STATUS
        return entry, f"检修计划已{action}"

    # ------------------------------------------------------------------ 顺延链路

    def _related_tasks(self, plan_code: str) -> list[dict[str, Any]]:
        return [
            task for task in store.rows(TASK_MODULE)
            if str(task.get("关联计划", "")).strip() == str(plan_code or "").strip()
        ]

    def _plan_shift(self, entry: dict[str, Any], days: int) -> dict[str, Any]:
        """计算单条计划顺延前后的差异（含关联任务），不落库。"""
        old_date = str(entry.get(DATE_FIELD, "") or "")
        new_date = _shift_date(old_date, days)
        tasks: list[dict[str, Any]] = []
        for task in self._related_tasks(str(entry.get("计划编号", ""))):
            task_change: dict[str, Any] = {
                "task_id": task.get("id"),
                "任务编号": task.get("任务编号"),
            }
            changed = False
            for field in TASK_DATE_FIELDS:
                old_value = str(task.get(field, "") or "")
                new_value = _shift_date(old_value, days)
                task_change[f"old_{field}"] = old_value
                task_change[f"new_{field}"] = new_value if new_value is not None else old_value
                if new_value is not None and new_value != old_value:
                    changed = True
            task_change["changed"] = changed
            tasks.append(task_change)
        return {
            "id": entry.get("id"),
            "计划编号": entry.get("计划编号"),
            "检修对象": entry.get("检修对象"),
            "status": entry.get("status"),
            "old_计划日期": old_date,
            "new_计划日期": new_date if new_date is not None else old_date,
            "date_shiftable": new_date is not None,
            "tasks": tasks,
        }

    def preview_postpone(
        self,
        *,
        ids: list[int] | None = None,
        days: int,
    ) -> tuple[dict[str, Any] | None, str]:
        if not isinstance(days, int) or days <= 0:
            return None, "顺延天数必须是大于 0 的整数"
        id_set = {int(item) for item in (ids or [])}
        targets = [
            store.find(MODULE, item_id)
            for item_id in id_set
            if store.find(MODULE, item_id) is not None
        ]
        if not targets:
            return None, "没有选中任何可顺延的检修计划"

        items: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for entry in targets:
            if entry.get("status") == VOID_STATUS:
                # 作废的不参与顺延，也不影响其余计划。
                skipped.append({"id": entry.get("id"), "计划编号": entry.get("计划编号"),
                                "reason": "已作废，不参与顺延"})
                continue
            items.append(self._plan_shift(entry, days))

        if not items:
            return None, "选中的计划均已作废，没有可顺延的记录"
        return {
            "days": days,
            "items": items,
            "skipped": skipped,
            "apply_count": len(items),
            "skip_count": len(skipped),
            "batch_no": None,
        }, ""

    def confirm_postpone(
        self,
        *,
        ids: list[int] | None = None,
        days: int,
        operator: str | None = None,
        opinion: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        if not isinstance(days, int) or days <= 0:
            return None, "顺延天数必须是大于 0 的整数"
        opinion = str(opinion or "").strip()
        if not opinion:
            return None, "请填写批复意见后再确认顺延"
        operator = operator or DEFAULT_OPERATOR
        id_set = {int(item) for item in (ids or [])}
        targets = [
            store.find(MODULE, item_id)
            for item_id in id_set
            if store.find(MODULE, item_id) is not None
        ]
        if not targets:
            return None, "没有选中任何可顺延的检修计划"

        batch_no = f"ADJ-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        at = _now()
        items: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for entry in targets:
            if entry.get("status") == VOID_STATUS:
                skipped.append({"id": entry.get("id"), "计划编号": entry.get("计划编号"),
                                "reason": "已作废，不参与顺延"})
                continue

            change = self._plan_shift(entry, days)
            old_date = change["old_计划日期"]
            new_date = change["new_计划日期"]

            # 计划日期整体后挪；日期解析不了时保留原值，仅留痕说明。
            if change["date_shiftable"]:
                entry[DATE_FIELD] = new_date

            # 关联计划明细（检修任务）同步后移。
            for task_change in change["tasks"]:
                task = store.find(TASK_MODULE, int(task_change["task_id"]))
                if task is None:
                    continue
                for field in TASK_DATE_FIELDS:
                    shifted = task_change.get(f"new_{field}")
                    if shifted is not None:
                        task[field] = shifted

            _append_history(entry, {
                "type": "顺延调整",
                "action": "顺延计划",
                "days": days,
                "from_date": old_date,
                "to_date": new_date,
                "synced_tasks": [tc["任务编号"] for tc in change["tasks"]],
                "operator": operator,
                "opinion": opinion,
                "batch_no": batch_no,
                "at": at,
            })
            items.append(change)

        if not items:
            return None, "选中的计划均已作废，未执行顺延"
        return {
            "days": days,
            "batch_no": batch_no,
            "items": items,
            "skipped": skipped,
            "apply_count": len(items),
            "skip_count": len(skipped),
            "operator": operator,
            "at": at,
        }, f"已顺延 {len(items)} 条检修计划（批次 {batch_no}）"
