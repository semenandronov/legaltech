"""
Assistant Chat V2 - Упрощённый thin controller

Использует ChatOrchestrator для обработки запросов.
Этот файл содержит только роутинг и парсинг запросов.
"""
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import logging
import json

from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.services.chat import (
    ChatOrchestrator,
    ChatRequest,
    get_chat_orchestrator,
    ChatHistoryService,
)
from app.services.chat.events import SSESerializer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assistant-chat-v2"])


def _normalize_bool(value) -> bool:
    """Нормализовать значение к bool"""
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


@router.post("/api/v2/assistant/chat")
async def assistant_chat_v2(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Streaming chat endpoint V2 (использует ChatOrchestrator)
    
    Accepts:
        - messages: array of {role, content}
        - case_id: ID дела
        - web_search: включить веб-поиск
        - legal_research: включить поиск НПА на pravo.gov.ru
        - deep_think: включить глубокое мышление
        - draft_mode: режим создания документа
        - document_context: контекст документа (для редактора)
        - document_id: ID документа
        - selected_text: выделенный текст
        - template_file_id: ID файла-шаблона
        - template_file_content: контент локального шаблона
        - attached_file_ids: прикреплённые файлы
        
    Returns:
        SSE stream с событиями
    """
    # #region agent log
    import json as json_module
    from datetime import datetime
    def _debug_log(location, message, data, hypothesis_id="C", run_id="chat_request"):
        log_entry = json_module.dumps({
            "sessionId": "debug-session",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(datetime.now().timestamp() * 1000)
        })
        try:
            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
                f.write(log_entry + '\n')
        except: pass
    # #endregion
    
    try:
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:64", "Request received", {"user_id": current_user.id if current_user else None}, hypothesis_id="C")
        except: pass
        # #endregion
        
        # Парсим тело запроса
        body = await request.json()
        
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:70", "Body parsed", {"has_messages": "messages" in body, "has_case_id": "case_id" in body or "caseId" in body}, hypothesis_id="C")
        except: pass
        # #endregion
        
        # Извлекаем параметры
        messages = body.get("messages", [])
        case_id = body.get("case_id") or body.get("caseId")
        
        if not case_id:
            # #region agent log
            try:
                _debug_log("assistant_chat_v2.py:75", "Validation failed", {"error": "case_id is required"}, hypothesis_id="C")
            except: pass
            # #endregion
            raise HTTPException(status_code=400, detail="case_id is required")
        
        if not messages:
            # #region agent log
            try:
                _debug_log("assistant_chat_v2.py:81", "Validation failed", {"error": "No messages provided"}, hypothesis_id="C")
            except: pass
            # #endregion
            raise HTTPException(status_code=400, detail="No messages provided")
        
        last_message = messages[-1]
        if last_message.get("role") != "user":
            # #region agent log
            try:
                _debug_log("assistant_chat_v2.py:87", "Validation failed", {"error": "Last message must be from user", "last_role": last_message.get("role")}, hypothesis_id="C")
            except: pass
            # #endregion
            raise HTTPException(status_code=400, detail="Last message must be from user")
        
        question = last_message.get("content", "")
        
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:93", "Question extracted", {"question_length": len(question), "case_id": case_id}, hypothesis_id="C")
        except: pass
        # #endregion
        
        # Нормализуем boolean параметры
        web_search = _normalize_bool(body.get("web_search", False))
        legal_research = _normalize_bool(body.get("legal_research", False))
        deep_think = _normalize_bool(body.get("deep_think", False))
        draft_mode = _normalize_bool(body.get("draft_mode", False))
        
        # Опциональные параметры
        document_context = body.get("document_context")
        document_id = body.get("document_id")
        selected_text = body.get("selected_text")
        editor_mode_hint = body.get("editor_mode_hint")  # 'edit' or 'ask' from UI toggle
        template_file_id = body.get("template_file_id")
        template_file_content = body.get("template_file_content")
        attached_file_ids = body.get("attached_file_ids")
        session_id = body.get("session_id") or None

        if attached_file_ids:
            logger.info(f"Attached file IDs: {attached_file_ids}")

        # Создаём ChatRequest
        chat_request = ChatRequest(
            case_id=case_id,
            question=question,
            current_user=current_user,
            web_search=web_search,
            legal_research=legal_research,
            deep_think=deep_think,
            draft_mode=draft_mode,
            document_context=document_context,
            document_id=document_id,
            selected_text=selected_text,
            template_file_id=template_file_id,
            template_file_content=template_file_content,
            attached_file_ids=attached_file_ids,
            editor_mode_hint=editor_mode_hint,
            session_id=session_id
        )
        
        # Создаём оркестратор и обрабатываем запрос
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:117", "Creating orchestrator", {"case_id": case_id}, hypothesis_id="C")
        except: pass
        # #endregion
        
        orchestrator = get_chat_orchestrator(db)
        
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:122", "Orchestrator created, starting stream", {"case_id": case_id, "question_length": len(question)}, hypothesis_id="C")
        except: pass
        # #endregion
        
        return StreamingResponse(
            orchestrator.process_request(chat_request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
        
    except HTTPException:
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:135", "HTTPException raised", {"status_code": "will_re_raise"}, hypothesis_id="C")
        except: pass
        # #endregion
        raise
    except Exception as e:
        # #region agent log
        try:
            import traceback
            _debug_log("assistant_chat_v2.py:140", "Exception caught", {"error": str(e), "error_type": type(e).__name__, "traceback": traceback.format_exc()}, hypothesis_id="C")
        except: pass
        # #endregion
        logger.error(f"Error in assistant_chat_v2: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v2/assistant/chat/{case_id}/sessions")
async def get_chat_sessions_v2(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить список сессий чата для дела
    """
    try:
        from app.models.case import Case
        
        # Проверяем доступ
        case = db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Получаем сессии через сервис
        history_service = ChatHistoryService(db)
        sessions = history_service.get_sessions_for_case(case_id)
        
        return {"sessions": sessions}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v2/assistant/chat/{case_id}/history")
async def get_chat_history_v2(
    case_id: str,
    session_id: Optional[str] = None,
    all_sessions: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить историю сообщений чата
    
    Args:
        case_id: ID дела
        session_id: ID конкретной сессии (опционально)
        all_sessions: Вернуть сообщения из всех сессий
    """
    try:
        from app.models.case import Case
        
        # Проверяем доступ
        case = db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Получаем историю через сервис
        history_service = ChatHistoryService(db)
        
        if all_sessions:
            messages = history_service.get_session_history(case_id, session_id=None)
        else:
            messages = history_service.get_session_history(case_id, session_id=session_id)
        
        # Форматируем сообщения
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "source_references": msg.source_references,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "session_id": msg.session_id
            })
        
        return {"messages": formatted_messages}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v2/assistant/chat/{case_id}/sessions/{session_id}")
async def delete_chat_session_v2(
    case_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Удалить сессию чата
    """
    try:
        from app.models.case import Case
        
        # Проверяем доступ
        case = db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Удаляем сессию через сервис
        history_service = ChatHistoryService(db)
        deleted_count = history_service.delete_session(case_id, session_id)
        
        return {"deleted": deleted_count}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v2/assistant/global-chat")
async def assistant_global_chat(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Global assistant chat endpoint (no case_id required).
    Saves messages to GlobalAssistantSession for history.
    """
    from app.models.case import GlobalAssistantSession, GlobalAssistantMessage
    from app.services.llm_factory import create_legal_llm
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    from datetime import datetime

    try:
        body = await request.json()
        messages = body.get("messages", [])
        session_id = body.get("session_id")  # optional: continue existing session
        file_contexts = list(body.get("file_contexts", []))  # [{filename, text}, ...]
        draft_mode = _normalize_bool(body.get("draft_mode", False))
        document_context = body.get("document_context")  # current draft content for refinement
        attached_file_ids = body.get("attached_file_ids") or []

        # Resolve attached case-file IDs → fetch text from DB
        if attached_file_ids:
            from app.models.case import File as CaseFile
            for fid in attached_file_ids:
                file_obj = db.query(CaseFile).filter(CaseFile.id == fid).first()
                if file_obj and file_obj.original_text:
                    file_contexts.append({
                        "filename": file_obj.filename,
                        "text": file_obj.original_text[:12000],
                        "file_id": fid,  # used for citation navigation
                    })

        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")

        last_message = messages[-1]
        if last_message.get("role") != "user":
            raise HTTPException(status_code=400, detail="Last message must be from user")

        question = last_message.get("content", "").strip()

        # Get or create session
        session = None
        if session_id:
            session = db.query(GlobalAssistantSession).filter(
                GlobalAssistantSession.id == session_id,
                GlobalAssistantSession.user_id == current_user.id
            ).first()

        if not session:
            session = GlobalAssistantSession(
                user_id=current_user.id,
                title=question[:200] if question else "Новый чат",
            )
            db.add(session)
            db.commit()
            db.refresh(session)

        # Save user message
        user_msg_db = GlobalAssistantMessage(
            session_id=session.id,
            role="user",
            content=question,
        )
        db.add(user_msg_db)
        db.commit()

        # Build LLM messages
        # use_rate_limiting=False for streaming SSE — avoids semaphore wait latency
        llm = create_legal_llm(use_rate_limiting=False)
        if draft_mode:
            system_content = (
                "Ты — профессиональный юридический составитель документов. "
                "Твоя задача — создавать структурированные, профессиональные юридические документы "
                "на основе описания пользователя. Используй профессиональный юридический язык, "
                "включай все необходимые разделы, оговорки и реквизиты. "
                "Форматируй документ чётко: заголовок, стороны, предмет договора, права и обязанности, "
                "условия, ответственность, заключительные положения, подписи. "
                "Не добавляй лишних пояснений — только сам документ.\n"
                "При доработке документа всегда выводи полный обновлённый текст.\n"
                "ВАЖНО: Никогда не используй разделители из точек (•••), дашей (---) или других символов "
                "для визуального разделения разделов. Используй только заголовки Markdown (## Раздел)."
            )
            if document_context:
                system_content += f"\n\n--- Текущий черновик документа ---\n{document_context}\n---"
        else:
            system_content = (
                "Ты — юридический AI-ассистент. Отвечай чётко, профессионально и по существу. "
                "На приветствия отвечай коротко и дружелюбно, например: 'Здравствуйте! Чем могу помочь?' "
                "Если вопрос выходит за пределы юридической тематики — отвечай всё равно полезно. "
                "Никогда не используй разделители из точек (•••), тире или других повторяющихся символов — "
                "только заголовки Markdown (## Раздел) для структурирования текста."
            )
        if file_contexts:
            system_content += "\n\nПользователь приложил следующие документы для анализа:\n"
            for i, fc in enumerate(file_contexts, start=1):
                fname = fc.get("filename", "документ")
                text = fc.get("text", "")
                system_content += f"\n--- [{i}] {fname} ---\n{text}\n"
            system_content += (
                "\n\nВАЖНО: При ответе ставь номер источника [1], [2] и т.д. "
                "сразу после каждого утверждения, которое основано на конкретном прикреплённом документе. "
                "Например: «Срок действия договора — 12 месяцев [1].»"
            )
        lc_messages = [SystemMessage(content=system_content)]
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))

        current_session_id = session.id

        async def generate():
            full_response = ""
            try:
                # Send session_id as first event so frontend can track it
                yield f'data: {json.dumps({"session_id": current_session_id})}\n\n'
                async for chunk in llm.astream(lc_messages):
                    text = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if text:
                        full_response += text
                        yield SSESerializer.text_delta(text)

                # Emit citations for attached files so frontend can render [N] badges
                if file_contexts:
                    citations = [
                        {
                            "source_id": fc.get("file_id") or "",
                            "file_name": fc.get("filename", "Документ"),
                            "quote": fc.get("text", "")[:400],
                            "source_type": "document",
                        }
                        for fc in file_contexts
                    ]
                    yield SSESerializer.citations(citations)

            except Exception as e:
                logger.error(f"Global chat LLM error: {e}", exc_info=True)
                yield SSESerializer.error(str(e))
            finally:
                # Save assistant response
                if full_response:
                    try:
                        from app.utils.database import SessionLocal
                        save_db = SessionLocal()
                        try:
                            asst_msg = GlobalAssistantMessage(
                                session_id=current_session_id,
                                role="assistant",
                                content=full_response,
                            )
                            save_db.add(asst_msg)
                            # Update session timestamp
                            save_db.query(GlobalAssistantSession).filter(
                                GlobalAssistantSession.id == current_session_id
                            ).update({"updated_at": datetime.utcnow()})
                            save_db.commit()
                        finally:
                            save_db.close()
                    except Exception as save_err:
                        logger.error(f"Failed to save global assistant message: {save_err}")

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Global chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v2/assistant/upload-file")
async def upload_file_for_assistant(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Extract text from an uploaded file for use as context in the global assistant.
    Returns the extracted text directly (no DB storage).
    """
    from app.services.langchain_loaders import DocumentLoaderService

    filename = file.filename or "document"
    content = await file.read()

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = {"pdf", "docx", "txt", "csv", "xlsx"}
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    if len(content) > 30 * 1024 * 1024:  # 30 MB
        raise HTTPException(status_code=400, detail="File too large (max 30 MB)")

    try:
        documents = DocumentLoaderService.load_document(content, filename)
        text = "\n\n".join(doc.page_content for doc in documents if doc.page_content.strip())
        # Truncate to ~100k chars to keep context manageable
        if len(text) > 100_000:
            text = text[:100_000] + "\n\n[...документ обрезан для контекста...]"
        return {"filename": filename, "text": text, "char_count": len(text)}
    except Exception as e:
        logger.error(f"File extraction error for {filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Не удалось извлечь текст из файла: {e}")


@router.post("/api/v2/assistant/download-docx")
async def download_draft_as_docx(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Convert draft document text to .docx and return for download."""
    from docx import Document as DocxDocument
    from docx.shared import Pt
    import io
    import re
    from fastapi.responses import Response

    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"download-docx: failed to parse JSON body: {e}")
        raise

    title = body.get("title", "Документ").strip()
    content = (body.get("content") or "").strip()
    content_type = body.get("content_type", "markdown")

    logger.info(f"download-docx: title={repr(title)}, content_type={content_type}, content_len={len(content)}")

    if not content:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "content is empty"}, status_code=400)

    try:
        doc = DocxDocument()

        # Title
        heading = doc.add_heading(title, level=0)
        if heading.runs:
            heading.runs[0].font.size = Pt(16)

        if content_type == "html":
            # Parse HTML content (from TipTap editor)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'ul', 'ol', 'hr'], recursive=True):
                if tag.parent and tag.parent.name in ['ul', 'ol']:
                    continue  # handled by parent
                if tag.name in ['h1', 'h2', 'h3', 'h4']:
                    level = int(tag.name[1])
                    h = doc.add_heading(tag.get_text(strip=True), level=min(level + 1, 9))
                    if h.runs:
                        h.runs[0].font.size = Pt(max(14 - (level - 1) * 2, 10))
                elif tag.name == 'p':
                    text = tag.get_text(strip=True)
                    if text:
                        doc.add_paragraph(text)
                elif tag.name in ['ul', 'ol']:
                    for li in tag.find_all('li', recursive=False):
                        prefix = '• ' if tag.name == 'ul' else ''
                        doc.add_paragraph(f"{prefix}{li.get_text(strip=True)}")
                elif tag.name == 'hr':
                    doc.add_paragraph('─' * 40)
        else:
            # Parse markdown content (legacy)
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            for para_text in paragraphs:
                if para_text.startswith("**") and para_text.endswith("**") and "\n" not in para_text:
                    h = doc.add_heading(para_text.strip("*").strip(), level=2)
                    h.runs[0].font.size = Pt(12)
                else:
                    clean = re.sub(r"\*\*(.*?)\*\*", r"\1", para_text)
                    doc.add_paragraph(clean)

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        import urllib.parse
        safe_title = re.sub(r'[^\w\s-]', '', title)[:60] or "document"
        ascii_title = safe_title.encode('ascii', 'ignore').decode().strip() or "document"
        encoded_title = urllib.parse.quote(safe_title.encode('utf-8'))
        content_disposition = f"attachment; filename=\"{ascii_title}.docx\"; filename*=UTF-8''{encoded_title}.docx"
        return Response(
            content=buf.read(),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": content_disposition},
        )
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"download-docx: failed to generate DOCX: {e}\n{tb}")
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e), "traceback": tb}, status_code=500)


@router.get("/api/v2/assistant/global-sessions")
async def get_global_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List global assistant sessions for the current user, newest first."""
    from app.models.case import GlobalAssistantSession, GlobalAssistantMessage
    from sqlalchemy import func

    sessions = (
        db.query(GlobalAssistantSession)
        .filter(GlobalAssistantSession.user_id == current_user.id)
        .order_by(GlobalAssistantSession.updated_at.desc())
        .limit(50)
        .all()
    )

    result = []
    for s in sessions:
        msg_count = db.query(func.count(GlobalAssistantMessage.id)).filter(
            GlobalAssistantMessage.session_id == s.id
        ).scalar() or 0
        result.append({
            "session_id": s.id,
            "title": s.title or "Без названия",
            "message_count": msg_count,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        })

    return result


@router.get("/api/v2/assistant/global-sessions/{session_id}")
async def get_global_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all messages for a global assistant session."""
    from app.models.case import GlobalAssistantSession, GlobalAssistantMessage

    session = db.query(GlobalAssistantSession).filter(
        GlobalAssistantSession.id == session_id,
        GlobalAssistantSession.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = db.query(GlobalAssistantMessage).filter(
        GlobalAssistantMessage.session_id == session_id
    ).order_by(GlobalAssistantMessage.created_at).all()

    return {
        "session_id": session.id,
        "title": session.title,
        "draft_title": session.draft_title,
        "draft_content": session.draft_content,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }


@router.patch("/api/v2/assistant/global-sessions/{session_id}/draft")
async def save_session_draft(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save or update the draft document associated with a global assistant session."""
    from app.models.case import GlobalAssistantSession
    body = await request.json()
    draft_title = body.get("draft_title", "")
    draft_content = body.get("draft_content", "")

    session = db.query(GlobalAssistantSession).filter(
        GlobalAssistantSession.id == session_id,
        GlobalAssistantSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.draft_title = draft_title
    session.draft_content = draft_content
    db.commit()
    return {"ok": True}


@router.get("/api/v2/recent-activity")
async def get_recent_activity(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return aggregated recent activity across all entity types for the current user,
    sorted by last-activity date (newest first).

    Entity types:
    - case_chat: in-case assistant session
    - global_chat: global (case-free) assistant session
    - tabular_review: tabular review project
    """
    from app.models.case import Case, ChatMessage, GlobalAssistantSession
    from app.models.tabular_review import TabularReview
    from sqlalchemy import func, desc

    PREVIEW = 80
    items = []

    # ── 1. Case chat sessions ──
    session_agg = (
        db.query(
            ChatMessage.case_id,
            ChatMessage.session_id,
            func.max(ChatMessage.created_at).label("last_at"),
        )
        .join(Case, Case.id == ChatMessage.case_id)
        .filter(
            Case.user_id == current_user.id,
            ChatMessage.session_id.isnot(None),
            ChatMessage.content.isnot(None),
            ChatMessage.content != "",
        )
        .group_by(ChatMessage.case_id, ChatMessage.session_id)
        .order_by(desc("last_at"))
        .limit(limit)
        .all()
    )

    if session_agg:
        case_ids = list({r.case_id for r in session_agg})
        cases_map = {
            c.id: (c.title or "Дело")
            for c in db.query(Case).filter(Case.id.in_(case_ids)).all()
        }
        for row in session_agg:
            first_msg = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.case_id == row.case_id,
                    ChatMessage.session_id == row.session_id,
                    ChatMessage.role == "user",
                    ChatMessage.content.isnot(None),
                    ChatMessage.content != "",
                )
                .order_by(ChatMessage.created_at.asc())
                .first()
            )
            content = first_msg.content if first_msg else ""
            title = content[:PREVIEW] + ("…" if len(content) > PREVIEW else "")
            items.append({
                "type": "case_chat",
                "id": row.session_id,
                "title": title or "Чат",
                "case_id": row.case_id,
                "case_name": cases_map.get(row.case_id, "Дело"),
                "updated_at": row.last_at.isoformat() if row.last_at else None,
            })

    # ── 2. Global assistant sessions ──
    global_sessions = (
        db.query(GlobalAssistantSession)
        .filter(GlobalAssistantSession.user_id == current_user.id)
        .order_by(desc(GlobalAssistantSession.updated_at))
        .limit(limit)
        .all()
    )
    for s in global_sessions:
        items.append({
            "type": "global_chat",
            "id": s.id,
            "title": s.title or "Новый чат",
            "case_id": None,
            "case_name": None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        })

    # ── 3. Tabular reviews ──
    reviews_q = (
        db.query(TabularReview, Case.title.label("case_title"))
        .join(Case, Case.id == TabularReview.case_id)
        .filter(TabularReview.user_id == current_user.id)
        .order_by(desc(TabularReview.updated_at))
        .limit(limit)
        .all()
    )
    for review, case_title in reviews_q:
        items.append({
            "type": "tabular_review",
            "id": review.id,
            "title": review.name or "Таблица",
            "case_id": review.case_id,
            "case_name": case_title or "Дело",
            "updated_at": review.updated_at.isoformat() if review.updated_at else None,
        })

    items.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return {"items": items[:limit]}
