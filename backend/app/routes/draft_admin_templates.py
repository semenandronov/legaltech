"""Админ: загрузка публичных шаблонов Draft (HTML в БД)."""
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import draft_admin_template_service as dts
from app.utils.auth import get_current_user
from app.utils.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin-draft-templates"])


@router.get("/api/v2/admin/draft-templates/status")
async def draft_templates_admin_status(current_user: User = Depends(get_current_user)):
    """Для UI: у авторизованного пользователя всегда есть доступ к странице шаблонов."""
    return {"is_template_admin": dts.is_draft_template_admin(current_user)}


@router.get("/api/v2/admin/draft-templates")
async def list_draft_templates_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {"templates": dts.list_admin_templates_for_management(db)}


@router.post("/api/v2/admin/draft-templates")
async def upload_draft_template_admin(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Не указано имя файла")
    content = await file.read()
    try:
        rec = dts.create_admin_draft_template(
            db,
            current_user,
            content,
            file.filename,
            title,
            description or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error("draft template upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Не удалось сохранить шаблон")

    fields_count = 0
    index_status = "not_indexed"
    try:
        from app.services.draft_template_catalog import load_catalog_snapshot
        from app.services.draft_template_keys import template_key_for_db_template

        snap = load_catalog_snapshot(db, template_key_for_db_template(str(rec.id)))
        if snap:
            fields_count = len(snap.field_specs)
            index_status = "indexed"
    except Exception:
        pass

    return {
        "id": rec.id,
        "title": rec.title,
        "description": rec.description or "",
        "content_length": len(rec.content or ""),
        "fields_count": fields_count,
        "index_status": index_status,
    }


@router.get("/api/v2/admin/draft-templates/{template_id}/fields")
async def get_draft_template_fields_admin(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return dts.get_admin_template_fields(db, template_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/v2/admin/draft-templates/{template_id}/reindex")
async def reindex_draft_template_admin(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return dts.reindex_admin_draft_template(db, current_user, template_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("draft template reindex failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Не удалось проиндексировать шаблон")


@router.delete("/api/v2/admin/draft-templates/{template_id}")
async def delete_draft_template_admin(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        ok = dts.delete_admin_draft_template(db, current_user, template_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    return {"ok": True}
