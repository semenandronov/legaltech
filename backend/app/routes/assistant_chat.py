"""Assistant UI chat endpoint for streaming responses"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import AsyncGenerator, Optional
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_memory import MemoryService
from app.services.llm_factory import create_llm
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize services
rag_service = RAGService()
document_processor = DocumentProcessor()
memory_service = MemoryService()


class AssistantMessage(BaseModel):
    """Message model for assistant-ui"""
    role: str = Field(..., description="Message role: user or assistant")
    content: str = Field(..., description="Message content")


# Note: Request body is parsed manually to support assistant-ui format
# Assistant-ui sends: { messages: [...], case_id: "..." }


async def stream_chat_response(
    case_id: str,
    question: str,
    db: Session,
    current_user: User
) -> AsyncGenerator[str, None]:
    """
    Stream chat response using RAG and LLM
    
    Yields:
        JSON strings in assistant-ui format
    """
    try:
        # Verify case ownership
        case = db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            yield f"data: {json.dumps({'error': 'Дело не найдено'})}\n\n"
            return
        
        # Get relevant documents using RAG (synchronous call)
        import asyncio
        loop = asyncio.get_event_loop()
        documents = await loop.run_in_executor(
            None,
            lambda: rag_service.retrieve_context(
                case_id=case_id,
                query=question,
                k=10,
                db=db
            )
        )
        
        # Build context from documents
        context_parts = []
        for i, doc in enumerate(documents[:5], 1):
            content = doc.get("content", "")[:500]  # Limit content length
            source = doc.get("file", "unknown")
            context_parts.append(f"[Документ {i}: {source}]\n{content}")
        
        context = "\n\n".join(context_parts)
        
        # Create prompt
        prompt = f"""Ты - юридический AI-ассистент. Ты помогаешь анализировать документы дела.

Контекст из документов дела:
{context}

Вопрос пользователя: {question}

Ответь на вопрос, используя информацию из документов. Если информации недостаточно, укажи это.
Будь точным и профессиональным."""

        # Initialize LLM
        llm = create_llm(temperature=0.7)
        
        # Stream response
        # Note: GigaChat streaming support may vary
        # For now, we'll simulate streaming by chunking the response
        try:
            # Check if LLM supports async streaming
            if hasattr(llm, 'astream'):
                full_response = ""
                async for chunk in llm.astream(prompt):
                    if hasattr(chunk, 'content'):
                        content = chunk.content
                    elif isinstance(chunk, str):
                        content = chunk
                    else:
                        content = str(chunk)
                    
                    full_response += content
                    
                    # Yield in assistant-ui format (SSE format)
                    # Assistant-ui expects: data: {"textDelta": "..."}
                    yield f"data: {json.dumps({'textDelta': content}, ensure_ascii=False)}\n\n"
                
                # Send completion (empty textDelta signals end)
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
            else:
                # Fallback: get full response and chunk it
                response = await loop.run_in_executor(None, lambda: llm.invoke(prompt))
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Simulate streaming by chunking
                chunk_size = 20
                for i in range(0, len(response_text), chunk_size):
                    chunk = response_text[i:i + chunk_size]
                    yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
                    # Small delay for streaming effect
                    await asyncio.sleep(0.05)
                
                yield f"data: {json.dumps({'textDelta': ''})}\n\n"
        except Exception as stream_error:
            logger.warning(f"Streaming failed, using fallback: {stream_error}")
            # Final fallback: get response synchronously and chunk
            response = await loop.run_in_executor(None, lambda: llm.invoke(prompt))
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            chunk_size = 20
            for i in range(0, len(response_text), chunk_size):
                chunk = response_text[i:i + chunk_size]
                yield f"data: {json.dumps({'textDelta': chunk}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.05)
            
            yield f"data: {json.dumps({'textDelta': ''})}\n\n"
    
    except Exception as e:
        logger.error(f"Error in stream_chat_response: {e}", exc_info=True)
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


@router.post("/api/chat")
async def assistant_chat(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Streaming chat endpoint for assistant-ui
    
    Accepts request body with messages array and case_id
    Returns Server-Sent Events (SSE) stream
    """
    try:
        # Parse request body
        body = await request.json()
        messages = body.get("messages", [])
        case_id = body.get("case_id") or body.get("caseId")
        
        if not case_id:
            raise HTTPException(status_code=400, detail="case_id is required")
        
        # Get last user message
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        last_message = messages[-1]
        if last_message.get("role") != "user":
            raise HTTPException(status_code=400, detail="Last message must be from user")
        
        question = last_message.get("content", "")
        
        # Create streaming response
        return StreamingResponse(
            stream_chat_response(
                case_id=case_id,
                question=question,
                db=db,
                current_user=current_user
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in assistant_chat endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

