"""Document AI Service for Legal AI Vault"""
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.llm_factory import create_legal_llm
from app.services.document_processor import DocumentProcessor
from langchain_core.messages import HumanMessage, SystemMessage
import logging
import re

logger = logging.getLogger(__name__)


class DocumentAIService:
    """Service for AI-powered document editing and generation"""
    
    def __init__(self, db: Session):
        """Initialize document AI service"""
        self.db = db
        self.rag_service = RAGService()
        self.document_processor = DocumentProcessor()
    
    def ai_assist(
        self,
        command: str,
        selected_text: str,
        case_id: str,
        document_content: str = "",
        prompt: str = ""
    ) -> Dict[str, Any]:
        """
        Main AI assistance method
        
        Args:
            command: AI command (create_contract, check_risks, improve, rewrite, simplify, custom)
            selected_text: Selected text from editor
            case_id: Case identifier
            document_content: Full document content (optional)
            prompt: Custom prompt (optional)
            
        Returns:
            Dictionary with result and suggestions
        """
        try:
            if command == "create_contract":
                return self.generate_contract(prompt, case_id)
            elif command == "check_risks":
                return self.check_risks(selected_text or document_content, case_id)
            elif command == "improve":
                return self.improve_text(selected_text or document_content, style="professional")
            elif command == "rewrite":
                return self.rewrite_text(selected_text or document_content, prompt or "Переписать более четко")
            elif command == "simplify":
                return self.simplify_text(selected_text or document_content)
            elif command == "custom":
                return self.custom_assist(prompt, selected_text, case_id, document_content)
            else:
                raise ValueError(f"Unknown command: {command}")
        except Exception as e:
            logger.error(f"Error in ai_assist: {e}", exc_info=True)
            return {
                "result": f"Ошибка: {str(e)}",
                "suggestions": []
            }
    
    async def generate_contract(
        self,
        prompt: str,
        case_id: str,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a contract based on prompt using template graph
        
        Args:
            prompt: Description of contract to generate
            case_id: Case identifier for context
            user_id: User identifier (optional, for template caching)
            document_id: Existing document ID (optional, for updating)
            
        Returns:
            Dictionary with generated contract text
        """
        try:
            from app.services.langchain_agents.legacy_stubs import create_template_graph, TemplateState
            from app.services.document_editor_service import DocumentEditorService
            
            # Создаем граф для работы с шаблонами
            graph = create_template_graph(self.db)
            
            # Инициализируем состояние для графа
            initial_state: TemplateState = {
                "user_query": prompt,
                "case_id": case_id,
                "user_id": user_id or "",
                "cached_template": None,
                "garant_template": None,
                "template_source": None,
                "final_template": None,
                "adapted_content": None,
                "document_id": document_id,
                "messages": [],
                "errors": [],
                "metadata": {},
                "should_adapt": True,  # Адаптируем шаблон под запрос
                "document_title": None
            }
            
            # Запускаем граф
            logger.info(f"[DocumentAIService] Running template graph for contract generation: {prompt[:100]}...")
            result = await graph.ainvoke(initial_state)
            
            if result.get("errors"):
                error_msg = "; ".join(result["errors"])
                logger.error(f"[DocumentAIService] Template graph errors: {error_msg}")
                # Fallback: возвращаем ошибку, но не падаем
                return {
                    "result": f"Ошибка при создании документа: {error_msg}",
                    "suggestions": []
                }
            
            # Если есть document_id, обновляем существующий документ
            if document_id and result.get("adapted_content"):
                try:
                    doc_service = DocumentEditorService(self.db)
                    doc_service.update_document(
                        document_id=document_id,
                        user_id=user_id or "",
                        content=result["adapted_content"],
                        create_version=True
                    )
                    logger.info(f"[DocumentAIService] Updated document {document_id} with template content")
                except Exception as update_error:
                    logger.error(f"[DocumentAIService] Error updating document: {update_error}")
            
            return {
                "result": result.get("adapted_content", ""),
                "suggestions": [
                    "Проверь на риски",
                    "Улучшить формулировки",
                    "Добавить пункт о штрафах"
                ],
                "template_source": result.get("template_source"),
                "document_id": result.get("document_id")
            }
        except Exception as e:
            logger.error(f"[DocumentAIService] Error in generate_contract: {e}", exc_info=True)
            # Fallback на старую логику если template_graph не работает
            return self._generate_contract_fallback(prompt, case_id)
    
    def _generate_contract_fallback(
        self,
        prompt: str,
        case_id: str
    ) -> Dict[str, Any]:
        """Fallback method for contract generation (old logic)"""
        # Get context from case documents
        context = ""
        try:
            # Retrieve relevant documents from case
            docs, _ = self.rag_service.generate_with_sources(
                case_id=case_id,
                query=f"Найди информацию о: {prompt}",
                k=5,
                db=self.db
            )
            if isinstance(docs, tuple):
                context_text, sources = docs
                context = context_text
            else:
                context = str(docs)
        except Exception as e:
            logger.warning(f"Could not retrieve context: {e}")
        
        # Create LLM prompt
        system_prompt = """Ты - опытный юрист, специализирующийся на составлении юридических документов.
Составь профессиональный юридический документ на основе запроса пользователя и контекста дела.
Используй юридическую терминологию и структуру, соответствующую российскому законодательству.
Документ должен быть четким, структурированным и готовым к использованию."""
        
        context_section = f'Контекст дела:\n{context}' if context else ''
        user_prompt = f"""Запрос: {prompt}

{context_section}

Составь профессиональный юридический документ. Используй структуру с нумерацией пунктов, четкими формулировками и всеми необходимыми разделами."""
        
        # Generate contract
        llm = create_legal_llm(temperature=0.3)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        result = response.content if hasattr(response, 'content') else str(response)
        
        return {
            "result": result,
            "suggestions": [
                "Проверь на риски",
                "Улучшить формулировки",
                "Добавить пункт о штрафах"
            ]
        }
    
    def check_risks(
        self,
        text: str,
        case_id: str
    ) -> Dict[str, Any]:
        """
        Check text for legal risks
        
        Args:
            text: Text to check
            case_id: Case identifier for context
            
        Returns:
            Dictionary with risk analysis, suggestions, and structured risks for highlighting
        """
        if not text:
            return {
                "result": "Нет текста для проверки",
                "suggestions": [],
                "risks": []
            }
        
        # Get context from case documents for comparison
        context = ""
        try:
            docs, _ = self.rag_service.generate_with_sources(
                case_id=case_id,
                query="Найди похожие документы и потенциальные риски",
                k=5,
                db=self.db
            )
            if isinstance(docs, tuple):
                context_text, sources = docs
                context = context_text
            else:
                context = str(docs)
        except Exception as e:
            logger.warning(f"Could not retrieve context: {e}")
        
        # Create LLM prompt with structured output for risk positions
        system_prompt = """Ты - опытный юрист-аналитик, специализирующийся на выявлении юридических рисков.
Проанализируй предоставленный текст на предмет потенциальных юридических рисков.

ФОРМАТ ОТВЕТА:
1. Сначала дай общий анализ рисков
2. Затем выведи JSON-блок со структурированными рисками:

```risks
[
  {"quote": "точная цитата проблемного фрагмента", "level": "high|medium|low", "description": "краткое описание риска"},
  ...
]
```

УРОВНИ РИСКОВ:
- high: критические юридические риски (недействительность, ответственность)
- medium: потенциальные проблемы (неоднозначные формулировки)
- low: рекомендации по улучшению"""
        
        context_for_comparison = f'Контекст дела для сравнения:\n{context}' if context else ''
        user_prompt = f"""Проанализируй следующий текст на юридические риски:

{text}

{context_for_comparison}

Найди риски и выведи их в указанном формате."""
        
        # Generate risk analysis
        llm = create_legal_llm(temperature=0.1)  # Low temperature for accuracy
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        result = response.content if hasattr(response, 'content') else str(response)
        
        # Parse structured risks from response
        risks = []
        import json
        import uuid
        
        # Extract risks JSON block
        risks_match = re.search(r'```risks\s*\n(.*?)\n```', result, re.DOTALL)
        if risks_match:
            try:
                risks_data = json.loads(risks_match.group(1))
                for risk_item in risks_data:
                    quote = risk_item.get("quote", "")
                    if quote and quote in text:
                        # Find position in text
                        start_pos = text.find(quote)
                        if start_pos != -1:
                            risks.append({
                                "id": f"risk-{uuid.uuid4().hex[:8]}",
                                "quote": quote,
                                "from": start_pos,
                                "to": start_pos + len(quote),
                                "level": risk_item.get("level", "medium"),
                                "description": risk_item.get("description", "")
                            })
            except json.JSONDecodeError as e:
                logger.warning(f"Could not parse risks JSON: {e}")
        
        return {
            "result": result,
            "suggestions": [
                "Исправить найденные риски",
                "Улучшить формулировки",
                "Добавить защитные пункты"
            ],
            "risks": risks
        }
    
    def improve_text(
        self,
        text: str,
        style: str = "professional"
    ) -> Dict[str, Any]:
        """
        Improve text quality
        
        Args:
            text: Text to improve
            style: Style to apply (professional, formal, concise)
            
        Returns:
            Dictionary with improved text
        """
        if not text:
            return {
                "result": "",
                "suggestions": []
            }
        
        style_descriptions = {
            "professional": "профессиональный юридический стиль",
            "formal": "официальный стиль",
            "concise": "краткий и четкий стиль"
        }
        
        system_prompt = f"""Ты - опытный редактор юридических текстов.
Улучши текст, сделав его более {style_descriptions.get(style, 'профессиональным')}, четким и юридически корректным.
Сохрани смысл, но улучши формулировки, структуру и читаемость.

ВАЖНО: Верни ТОЛЬКО улучшенный текст. Без вступлений, пояснений, комментариев, заголовков вроде "Улучшенная версия:" и т.п.
Просто замени исходный текст на улучшенную версию. Длина результата должна быть примерно такой же, как у исходного текста."""

        user_prompt = f"""Улучши следующий текст (верни только результат, без пояснений):

{text}"""
        
        llm = create_legal_llm(temperature=0.2)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        result = response.content if hasattr(response, 'content') else str(response)
        
        return {
            "result": result,
            "suggestions": []
        }
    
    def rewrite_text(
        self,
        text: str,
        instruction: str
    ) -> Dict[str, Any]:
        """
        Rewrite text according to instruction
        
        Args:
            text: Text to rewrite
            instruction: Instruction for rewriting
            
        Returns:
            Dictionary with rewritten text
        """
        if not text:
            return {
                "result": "",
                "suggestions": []
            }
        
        system_prompt = """Ты - опытный редактор юридических текстов.
Перепиши текст согласно инструкции пользователя, сохранив юридическую корректность и смысл.

ВАЖНО: Верни ТОЛЬКО переписанный текст. Без вступлений, пояснений, комментариев и заголовков.
Просто замени исходный текст на переписанную версию."""

        user_prompt = f"""Перепиши следующий текст (верни только результат):

{text}

Инструкция: {instruction}"""
        
        llm = create_legal_llm(temperature=0.3)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        result = response.content if hasattr(response, 'content') else str(response)
        
        return {
            "result": result,
            "suggestions": []
        }
    
    def simplify_text(
        self,
        text: str
    ) -> Dict[str, Any]:
        """
        Simplify text for non-specialists
        
        Args:
            text: Text to simplify
            
        Returns:
            Dictionary with simplified text
        """
        if not text:
            return {
                "result": "",
                "suggestions": []
            }
        
        system_prompt = """Ты - опытный редактор, специализирующийся на упрощении юридических текстов.
Упрости текст, сделав его понятным для неспециалистов, но сохрани юридическую точность и смысл.
Замени сложные юридические термины на более простые, где это возможно без потери смысла.

ВАЖНО: Верни ТОЛЬКО упрощённый текст. Без вступлений, пояснений, комментариев и заголовков.
Просто замени исходный текст на упрощённую версию."""

        user_prompt = f"""Упрости следующий текст (верни только результат):

{text}"""
        
        llm = create_legal_llm(temperature=0.2)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        result = response.content if hasattr(response, 'content') else str(response)
        
        return {
            "result": result,
            "suggestions": []
        }
    
    def find_similar_clauses(
        self,
        text: str,
        case_id: str
    ) -> Dict[str, Any]:
        """
        Find similar clauses in case documents
        
        Args:
            text: Text to find similar clauses for
            case_id: Case identifier
            
        Returns:
            Dictionary with similar clauses
        """
        if not text:
            return {
                "result": "",
                "suggestions": []
            }
        
        # Use RAG to find similar content
        try:
            docs, sources = self.rag_service.generate_with_sources(
                case_id=case_id,
                query=f"Найди похожие формулировки и пункты для: {text}",
                k=5,
                db=self.db
            )
            
            if isinstance(docs, tuple):
                result_text, source_list = docs
            else:
                result_text = str(docs)
                source_list = []
            
            return {
                "result": result_text,
                "suggestions": [f"Источник: {s.get('file', 'Неизвестно')}" for s in source_list[:3]],
                "sources": source_list
            }
        except Exception as e:
            logger.error(f"Error finding similar clauses: {e}", exc_info=True)
            return {
                "result": f"Ошибка при поиске похожих пунктов: {str(e)}",
                "suggestions": []
            }
    
    def custom_assist(
        self,
        prompt: str,
        selected_text: str,
        case_id: str,
        document_content: str
    ) -> Dict[str, Any]:
        """
        Custom AI assistance based on user prompt
        
        Args:
            prompt: User's custom prompt
            selected_text: Selected text (if any)
            case_id: Case identifier
            document_content: Full document content
            
        Returns:
            Dictionary with result
        """
        # Get context from case if needed
        context = ""
        if case_id:
            try:
                docs, _ = self.rag_service.generate_with_sources(
                    case_id=case_id,
                    query=prompt,
                    k=3,
                    db=self.db
                )
                if isinstance(docs, tuple):
                    context_text, sources = docs
                    context = context_text
                else:
                    context = str(docs)
            except Exception as e:
                logger.warning(f"Could not retrieve context: {e}")
        
        system_prompt = """Ты - опытный AI-ассистент для работы с юридическими документами.
Помоги пользователю выполнить его запрос, используя контекст дела и содержимое документа.
Будь точным, профессиональным и полезным."""
        
        selected_text_section = f'Выделенный текст:\n{selected_text}' if selected_text else ''
        doc_content_section = f'Полное содержимое документа:\n{document_content[:2000]}' if document_content else ''
        case_context_section = f'Контекст дела:\n{context}' if context else ''
        
        user_prompt = f"""Запрос пользователя: {prompt}

{selected_text_section}

{doc_content_section}

{case_context_section}

Выполни запрос пользователя."""
        
        llm = create_legal_llm(temperature=0.3)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        result = response.content if hasattr(response, 'content') else str(response)
        
        return {
            "result": result,
            "suggestions": []
        }
    
    async def chat_over_document(
        self,
        document_id: Optional[str],
        document_content: str,
        case_id: str,
        question: str,
        mode: str = "ask",
        selected_text: Optional[str] = None,
        user_id: Optional[str] = None,
        deep_think: bool = False,
        legal_research: bool = False,
        selection_range: Optional[Dict[str, int]] = None,
        attached_file_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Deprecated: delegates to EditorChatBridge (LangGraph).

        Kept for backward compatibility with legacy callers.
        """
        from app.models.user import User
        from app.services.editor_chat_bridge import EditorChatBridge

        mode = mode if mode in ("ask", "edit", "draft") else "ask"
        if not user_id:
            raise ValueError("user_id is required for chat_over_document")
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User not found: {user_id}")

        logger.warning(
            "[DocumentAI] chat_over_document is deprecated; routed via EditorChatBridge"
        )
        bridge = EditorChatBridge(self.db, self.rag_service)
        return await bridge.run(
            case_id=case_id,
            user=user,
            document_id=document_id or "",
            document_content=document_content or "",
            question=question,
            mode=mode,
            selected_text=selected_text,
            selection_range=selection_range,
            attached_file_ids=attached_file_ids,
            deep_think=deep_think,
            legal_research=legal_research,
        )

