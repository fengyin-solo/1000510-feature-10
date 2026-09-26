"""检修计划接口：维护检修计划，覆盖提交审批、确认执行、作废与整组顺延链路。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    EntryPayload,
    PageResult,
    PlanActionPayload,
    PlanPostponeApplyPayload,
    PlanPostponePreviewPayload,
)
from app.services.plan import PlanService

router = APIRouter(prefix="/api/plan", tags=["检修计划"])

service = PlanService()

LIST_FIELDS = ["计划编号", "检修类型", "检修对象", "计划日期", "检修周期", "作业班组", "计划工时"]
STATUSES = ["待审批", "已批复", "执行中", "已作废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号检索"),
    status: str | None = Query(default=None, description="待审批、已批复、执行中、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计划编号与状态过滤检修计划列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条检修计划，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="检修计划已登记", entry=entry)


@router.post("/postpone/preview", response_model=ActionResult)
def postpone_preview(payload: PlanPostponePreviewPayload) -> ActionResult:
    """整组顺延前的预览：给出每条计划与关联明细的日期变化，已作废计划单列跳过。"""
    preview, message = service.postpone_preview(payload.plan_ids, payload.days)
    if preview is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="顺延预览已生成", entry=preview)


@router.post("/postpone/apply", response_model=ActionResult)
def postpone_apply(payload: PlanPostponeApplyPayload) -> ActionResult:
    """确认顺延：按预览整体后移计划日期并同步关联明细，落操作人与批复意见。"""
    result, message = service.postpone_apply(
        payload.plan_ids, payload.days, comment=payload.comment, operator=payload.operator
    )
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出检修计划清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "plan", "total": total, "items": items}


@router.get("/{entry_id}/histories", response_model=ActionResult)
def list_histories(entry_id: int) -> ActionResult:
    """读取一条检修计划的调整留痕：每次状态流转、顺延的操作人与批复意见都在里面。"""
    histories, message = service.list_histories(entry_id)
    if histories is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(
        ok=True,
        message=f"共 {len(histories)} 条调整记录",
        entry={"id": entry_id, "histories": histories},
    )


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检修计划明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检修计划 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: PlanActionPayload) -> ActionResult:
    """对单条检修计划执行提交审批、确认执行、作废计划；状态只许向前推进，每次动作留痕。"""
    action = (payload.action or str(payload.values.get("action") or "")).strip()
    entry, message = service.run_action(
        entry_id, action, operator=payload.operator, comment=payload.comment
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
