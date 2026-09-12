# [新增 2026-09-09] 标识维修记录路由：分页查询 / 计数 / xlsx与CSV导出（同一筛选口径）
# 权限：signage.repair（维修记录查看/导出）
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from urllib.parse import quote
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, has_permission, PERM_SIGNAGE_REPAIR
from app.models.user import User
from app.services import signage_repair_service as svc
from app.utils import beijing_now

router = APIRouter(prefix="/api/signage-repairs", tags=["标识维修记录"])


def _repair_filters(
    keyword: str | None = Query(None, description="标识编码/名称关键词"),
    signage_id: int | None = Query(None, description="标识ID（精确筛选）"),
    start_date: str | None = Query(None, description="发起时间起（YYYY-MM-DD，按北京日期）"),
    end_date: str | None = Query(None, description="发起时间止（YYYY-MM-DD，含当天）"),
    repair_party: str | None = Query(None, description="维修方：vendor=供应商 / engineering=工程部"),
    supplier_id: int | None = Query(None, description="供应商ID（供应商维修时联动筛选）"),
    status: str | None = Query(None, description="维修状态：in_progress=进行中 / completed=已完成"),
):
    for name, v in (("start_date", start_date), ("end_date", end_date)):
        if v:
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=422, detail=f"{name} 格式应为 YYYY-MM-DD")
    return {
        "keyword": keyword, "signage_id": signage_id,
        "start_date": start_date, "end_date": end_date,
        "repair_party": repair_party, "supplier_id": supplier_id, "status": status,
    }


def _check_perm(current_user: User):
    if not has_permission(current_user, PERM_SIGNAGE_REPAIR):
        raise HTTPException(status_code=403, detail="权限不足")


@router.get("")
def list_repairs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    filters: dict = Depends(_repair_filters),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页查询全部标识维修记录（含维修前/后照片路径与标识位置信息）"""
    _check_perm(current_user)
    items, total = svc.list_repairs(db, page=page, page_size=page_size, **filters)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/count")
def count_repairs(
    filters: dict = Depends(_repair_filters),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按筛选条件统计条数（导出确认弹窗展示导出范围）"""
    _check_perm(current_user)
    return {"total": svc.count_repairs(db, **filters)}


def _file_response(buf, filename: str, media_type: str):
    """[新增 2026-09-09] 统一文件下载响应（RFC 5987 中文文件名编码）"""
    headers = {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)}
    return StreamingResponse(buf, media_type=media_type, headers=headers)


def _export_filename(ext: str) -> str:
    stamp = beijing_now().strftime("%Y%m%d_%H%M%S")
    return "维修记录_" + stamp + "." + ext


@router.get("/export.xlsx")
def export_repairs_xlsx(
    filters: dict = Depends(_repair_filters),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按当前筛选条件导出维修记录 Excel"""
    _check_perm(current_user)
    output = svc.export_repairs_xlsx(db, **filters)
    return _file_response(
        output, _export_filename("xlsx"),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("/export.csv")
def export_repairs_csv(
    filters: dict = Depends(_repair_filters),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按当前筛选条件导出维修记录 CSV（utf-8-sig，Excel 中文不乱码）"""
    _check_perm(current_user)
    output = svc.export_repairs_csv(db, **filters)
    return _file_response(output, _export_filename("csv"), "text/csv; charset=utf-8")
