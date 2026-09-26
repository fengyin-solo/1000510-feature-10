"""检修计划业务规则：状态流转、顺延链路、留痕与关联明细同步都收在这里。

状态只允许沿 待审批 → 已批复 → 执行中 → 已作废 往前推进：
- 提交审批：待审批 → 已批复
- 确认执行：已批复 → 执行中（老动作，语义保持不变）
- 作废计划：任意未作废状态 → 已作废，作废后不能再改回任何状态
- 计划顺延：不改状态，只整体后移计划日期，并同步关联检修任务明细的起止时间

每一次调整都会写入「调整记录」，落操作人、批复意见与时间。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

MODULE = "plan"
TASK_MODULE = "task"
REQUIRED_FIELDS = ["计划编号", "检修类型", "检修对象"]
STATUS_ORDER = ["待审批", "已批复", "执行中", "已作废"]
VOID_STATUS = "已作废"
# 普通动作必须逐档向前；作废可以从任意未作废档位跳入终态。
ACTION_RULES = {"提交审批": "已批复", "确认执行": "执行中", "作废计划": "已作废"}
NEGATIVE_ACTIONS = ["作废计划"]
DATE_FMT = "%Y-%m-%d"
# 顺延触发后，关联检修任务里需要一起后移的日期字段。
DETAIL_DATE_FIELDS = ["开始时间", "完成时间"]
DEFAULT_OPERATOR = "值班管理员"


class PlanService:
    # ------------------------------------------------------------------ 列表
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
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            self._ensure_meta(entry)
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        if str(values.get("计划日期") or "").strip():
            entry["计划日期"] = str(values.get("计划日期")).strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["调整记录"] = []
        rows.append(entry)
        return entry, []

    # ------------------------------------------------------------------ 留痕
    def list_histories(self, entry_id: int) -> tuple[list[dict[str, Any]] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检修计划 {entry_id} 不存在或已归档"
        return list(self._ensure_meta(entry).get("调整记录", [])), ""

    def _append_history(self, entry: dict[str, Any], record: dict[str, Any]) -> None:
        records = self._ensure_meta(entry).setdefault("调整记录", [])
        record.setdefault("seq", len(records) + 1)
        record.setdefault("operated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        records.append(record)

    @staticmethod
    def _ensure_meta(entry: dict[str, Any]) -> dict[str, Any]:
        entry.setdefault("调整记录", [])
        return entry

    @staticmethod
    def _operator(value: str | None) -> str:
        operator = str(value or "").strip()
        return operator or DEFAULT_OPERATOR

    # -------------------------------------------------------------- 状态流转
    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str | None = None,
        comment: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"检修计划 {entry_id} 不存在或已归档"
        self._ensure_meta(entry)
        current = str(entry.get("status") or "")
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于检修计划可执行范围"
        target = ACTION_RULES[action]

        if current == VOID_STATUS:
            return None, "计划已作废，状态不能改回任何档位"
        if action == "作废计划":
            # 作废是向终态推进，任意未作废档位都允许，且不可逆转。
            pass
        else:
            current_index = STATUS_ORDER.index(current) if current in STATUS_ORDER else -1
            target_index = STATUS_ORDER.index(target)
            if current_index < 0 or target_index != current_index + 1:
                return None, f"计划当前为「{current}」，状态只能向前推进，不能执行{action}"

        entry["status"] = target
        entry["pending"] = target != VOID_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        self._append_history(entry, {
            "action": action,
            "from_status": current,
            "to_status": target,
            "operator": self._operator(operator),
            "comment": str(comment or "").strip() or "—",
        })
        return entry, f"检修计划已{action}"

    # ------------------------------------------------------------------ 顺延
    def postpone_preview(
        self, plan_ids: list[int], days: int
    ) -> tuple[dict[str, Any] | None, str]:
        message = self._validate_postpone(plan_ids, days)
        if message:
            return None, message
        return self._build_preview(plan_ids, days), ""

    def postpone_apply(
        self,
        plan_ids: list[int],
        days: int,
        *,
        comment: str | None = None,
        operator: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        opinion = str(comment or "").strip()
        message = self._validate_postpone(plan_ids, days)
        if message:
            return None, message
        if not opinion:
            return None, "请填写批复意见后再确认顺延"

        preview = self._build_preview(plan_ids, days)
        actor = self._operator(operator)
        operated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        postponed: list[dict[str, Any]] = []

        # 以预览为基准落库：已作废/不存在的条目在预览里已被排除，不会影响其他计划。
        for item in preview["plans"]:
            entry = store.find(MODULE, int(item["id"]))
            if entry is None or entry.get("status") == VOID_STATUS:
                continue
            current_status = str(entry.get("status") or "")
            if item.get("date_shifted"):
                entry["计划日期"] = item["date_to"]
            for detail in item.get("linked_details", []):
                task = store.find(TASK_MODULE, int(detail["id"]))
                if task is None:
                    continue
                for field in DETAIL_DATE_FIELDS:
                    shift = detail.get("shifts", {}).get(field)
                    if shift and shift.get("shifted"):
                        task[field] = shift["to"]
            self._append_history(entry, {
                "action": "计划顺延",
                "from_status": current_status,
                "to_status": current_status,
                "operator": actor,
                "comment": opinion,
                "days": days,
                "date_from": item.get("date_from") or "",
                "date_to": item.get("date_to") or "",
                "linked_count": len(item.get("linked_details", [])),
                "operated_at": operated_at,
            })
            postponed.append(item)

        if not postponed:
            return None, "所选计划均为已作废或不存在，未执行顺延"

        result = {
            "days": days,
            "comment": opinion,
            "operator": actor,
            "postponed": postponed,
            "excluded": preview["excluded"],
        }
        skipped = len(preview["excluded"])
        message = f"已顺延 {len(postponed)} 条计划（整体后移 {days} 天），关联明细已同步"
        if skipped:
            message += f"；{skipped} 条已作废或不存在的计划已跳过，未受影响"
        return result, message

    @staticmethod
    def _validate_postpone(plan_ids: list[int], days: int) -> str:
        if not plan_ids:
            return "请至少选择一条检修计划后再顺延"
        if not isinstance(days, int) or days < 1:
            return "顺延天数必须是大于 0 的整数"
        return ""

    def _build_preview(self, plan_ids: list[int], days: int) -> dict[str, Any]:
        """组装顺延预览：逐条给出日期变化与关联明细变化，作废/缺失单列。"""
        plans: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        seen: set[int] = set()

        for raw_id in plan_ids:
            entry_id = int(raw_id)
            if entry_id in seen:
                continue
            seen.add(entry_id)
            entry = store.find(MODULE, entry_id)
            if entry is None:
                excluded.append({
                    "id": entry_id, "计划编号": None,
                    "reason": "检修计划不存在或已归档，已跳过",
                })
                continue
            if entry.get("status") == VOID_STATUS:
                excluded.append({
                    "id": entry_id,
                    "计划编号": entry.get("计划编号"),
                    "reason": "计划已作废，不参与顺延，不影响其他计划",
                })
                continue

            date_from = str(entry.get("计划日期") or "").strip()
            date_to, date_shifted = self._shift_date(date_from, days)
            linked_details = self._linked_detail_shifts(entry, days)
            plans.append({
                "id": entry_id,
                "计划编号": entry.get("计划编号"),
                "检修对象": entry.get("检修对象"),
                "status": entry.get("status"),
                "date_from": date_from,
                "date_to": date_to,
                "date_shifted": date_shifted,
                "linked_details": linked_details,
            })

        return {"days": days, "plans": plans, "excluded": excluded}

    def _linked_detail_shifts(self, plan_entry: dict[str, Any], days: int) -> list[dict[str, Any]]:
        """找出与计划编号关联的检修任务明细，预演各日期字段的后移结果。"""
        plan_no = str(plan_entry.get("计划编号") or "").strip()
        if not plan_no:
            return []
        details: list[dict[str, Any]] = []
        for task in store.rows(TASK_MODULE):
            if str(task.get("关联计划") or "").strip() != plan_no:
                continue
            shifts: dict[str, dict[str, Any]] = {}
            any_shifted = False
            for field in DETAIL_DATE_FIELDS:
                to_value, shifted = self._shift_date(str(task.get(field) or "").strip(), days)
                shifts[field] = {"from": task.get(field), "to": to_value, "shifted": shifted}
                any_shifted = any_shifted or shifted
            details.append({
                "id": task.get("id"),
                "任务编号": task.get("任务编号"),
                "shifts": shifts,
                "shifted": any_shifted,
            })
        return details

    @staticmethod
    def _shift_date(value: str, days: int) -> tuple[str, bool]:
        """把 YYYY-MM-DD 日期后移；解析不了的值原样返回并标记 shifted=False。"""
        text = str(value or "").strip()
        if not text:
            return "", False
        try:
            shifted = (datetime.strptime(text, DATE_FMT) + timedelta(days=days)).strftime(DATE_FMT)
        except ValueError:
            return text, False
        return shifted, True
