"""Upload route for Legal AI Vault"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from typing import List
from sqlalchemy.orm import Session
from app.utils.file_parser import parse_file
from app.utils.database import get_db
from app.models.case import Case
from app.config import config
import uuid

router = APIRouter()


@router.post("/", include_in_schema=True)
@router.post("", include_in_schema=False)  # Also handle without trailing slash
async def upload_files(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload files and extract text content
    
    Supports: PDF, DOCX, TXT, XLSX
    Returns: case_id, num_files, file_names, status, message
    """
    if not files:
        raise HTTPException(status_code=400, detail="Не загружено ни одного файла")
    
    # Validate file extensions
    allowed_extensions = [ext.replace(".", "") for ext in config.ALLOWED_EXTENSIONS]
    file_names = []
    text_parts = []
    
    for file in files:
        # Check extension
        _, ext = file.filename.rsplit(".", 1) if "." in file.filename else (file.filename, "")
        if ext.lower() not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Файл '{file.filename}' имеет неподдерживаемый формат. Поддерживаются: {', '.join(allowed_extensions)}"
            )
        
        # Check file size
        content = await file.read()
        if len(content) > config.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Файл '{file.filename}' слишком большой. Максимальный размер: {config.MAX_FILE_SIZE / 1024 / 1024} МБ"
            )
        
        # Parse file
        try:
            text = parse_file(content, file.filename)
            # Add separator with filename
            text_parts.append(f"[{file.filename}]\n{text}")
            file_names.append(file.filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при обработке файла '{file.filename}': {str(e)}"
            )
    
    # Combine all text
    full_text = "\n\n".join(text_parts)
    
    # Create case
    case_id = str(uuid.uuid4())
    case = Case(
        id=case_id,
        full_text=full_text,
        num_documents=len(file_names),
        file_names=file_names,
        title=f"Дело из {len(file_names)} документов"
    )
    
    db.add(case)
    db.commit()
    db.refresh(case)
    
    return {
        "case_id": case_id,
        "num_files": len(file_names),
        "file_names": file_names,
        "status": "success",
        "message": f"Загружено {len(file_names)} файлов. Готово к чату!"
    }

