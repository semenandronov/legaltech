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
        legal_research: bool = False
    ) -> Dict[str, Any]:
        """
        Chat over document - ask questions and get AI to edit the document
        
        Args:
            document_id: Document identifier
            document_content: Current document content
            case_id: Case identifier for context
            question: User question/instruction
            user_id: User identifier (optional, for template caching)
            deep_think: Enable deep thinking mode for complex questions
            legal_research: Enable legal research mode
            
        Returns:
            Dictionary with answer and suggested edits
        """
        import re
        import uuid

        # Normalize mode (fallback to ask for unknown values)
        mode = mode if mode in ("ask", "edit", "draft") else "ask"
        logger.info(f"[DocumentAI] chat_over_document mode={mode} question={question[:80]!r}")

        # ── RAG: retrieve case context (used in all modes) ──────────────────
        context = ""
        sources: List = []
        try:
            docs, source_list = self.rag_service.generate_with_sources(
                case_id=case_id,
                query=question,
                k=5,
                db=self.db
            )
            if isinstance(docs, tuple):
                context_text, source_list = docs
                context = context_text
            else:
                context = str(docs)
                source_list = []
            sources = source_list
        except Exception as e:
            logger.warning(f"Could not retrieve context: {e}")

        doc_limit = 15000
        doc_preview = document_content[:doc_limit] if document_content else ""
        doc_truncated = (
            f"\n[... документ обрезан, показано {doc_limit} из {len(document_content)} символов ...]"
            if document_content and len(document_content) > doc_limit else ""
        )
        other_docs_context = (
            f'=== КОНТЕКСТ ИЗ ДРУГИХ ДОКУМЕНТОВ ДЕЛА ===\n{context}\n=== КОНЕЦ КОНТЕКСТА ==='
            if context else ''
        )

        # ═══════════════════════════════════════════════════════════════════
        # ASK MODE — pure Q&A, no editing
        # ═══════════════════════════════════════════════════════════════════
        if mode == "ask":
            system_prompt = (
                "Ты — AI-ассистент для анализа юридических документов. Сейчас ты работаешь в режиме Ask (вопросы и ответы).\n"
                "Отвечай на вопросы подробно и профессионально.\n"
                "Цитируй конкретные пункты документа там, где это уместно.\n"
                "Не используй Markdown-форматирование (**, *, ##) — пиши обычным текстом.\n\n"
                "ВАЖНО: если пользователь просит что-то изменить, переписать, отредактировать, добавить или удалить текст — "
                "не выполняй редактирование. Вместо этого кратко и по-дружески ответь, что для этого нужно переключиться "
                "в режим Edit (для правок существующего текста) или Draft (для создания нового текста), "
                "нажав на кнопку режима в поле ввода. Одно-два предложения, без лишних объяснений."
            )
            doc_section = f"=== ДОКУМЕНТ ===\n{doc_preview}{doc_truncated}\n=== КОНЕЦ ===" if document_content else ""
            user_prompt = f"ВОПРОС: {question}\n\n{doc_section}\n\n{other_docs_context}\n\nОтветь на вопрос."

            llm = create_legal_llm(temperature=0.2)
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            answer = response.content if hasattr(response, "content") else str(response)
            answer = re.sub(r'```[\s\S]*?```', '', answer, flags=re.DOTALL).strip()

            return {
                "answer": answer,
                "citations": [{"file": s.get("file", "Документ дела"), "file_id": s.get("file_id", "")} for s in sources[:3]],
                "suggestions": [],
                "structured_edits": [],
            }

        # ═══════════════════════════════════════════════════════════════════
        # DRAFT MODE — generate text snippet to insert at cursor position
        # The frontend inserts the answer text directly at the cursor position.
        # We do NOT return the full document — only the new fragment.
        # ═══════════════════════════════════════════════════════════════════
        if mode == "draft":
            system_prompt = (
                "Ты — AI-ассистент для юридических документов. Сейчас ты работаешь в режиме Draft.\n"
                "Пользователь поставил курсор в нужное место документа и просит создать текст для вставки.\n\n"
                "ПРАВИЛА:\n"
                "- Верни ТОЛЬКО текст нового фрагмента — без вступлений, без пояснений, без markdown.\n"
                "- Пиши профессионально, в стиле юридического документа на русском языке.\n"
                "- Не добавляй HTML-теги, если только пользователь явно не просит форматирование.\n"
                "- Не начинай ответ со слов «Конечно», «Вот», «Я напишу» и т.п.\n"
                "- Первое слово ответа — уже текст для вставки."
            )
            doc_context = (
                f"\n\n=== КОНТЕКСТ ДОКУМЕНТА ===\n{doc_preview[:3000]}\n=== КОНЕЦ ==="
                if document_content else ""
            )
            rag_context = f"\n\n{other_docs_context}" if other_docs_context else ""
            user_prompt = f"ЗАПРОС: {question}{doc_context}{rag_context}\n\nСгенерируй текст для вставки."

            llm = create_legal_llm(temperature=0.4)
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            answer = response.content if hasattr(response, "content") else str(response)
            answer = re.sub(r'```[\s\S]*?```', '', answer, flags=re.DOTALL).strip()

            return {
                "answer": answer,
                "citations": [],
                "suggestions": [],
                "structured_edits": [],
            }

        # ═══════════════════════════════════════════════════════════════════
        # EDIT MODE — modify existing document
        # If selected_text provided — always targeted replacement of that text.
        # Otherwise: targeted if keywords match, full HTML otherwise.
        # ═══════════════════════════════════════════════════════════════════
        # mode == "edit"
        targeted_keywords = [
            " на ", "замени", "поменяй", "вместо", "заменить на",
            "поставь", "впиши", "укажи", "обнови значение",
        ]
        has_file_reference = "[файл:" in question.lower() or "[file:" in question.lower()
        # selected_text forces targeted mode — user is working on a specific fragment
        use_targeted = bool(selected_text) or any(kw in question.lower() for kw in targeted_keywords) or has_file_reference

        if selected_text:
            # ── Selected-text mode ──────────────────────────────────────────────
            # Ask LLM only for the replacement text using simple labeled format.
            # We set original_text = selected_text ourselves (100% accurate).
            # The frontend applies at exact {from, to} positions — no text search.
            system_prompt = (
                "Ты — AI-ассистент для точечного редактирования юридических текстов.\n\n"
                "Пользователь выделил конкретный фрагмент и хочет применить к нему инструкцию.\n\n"
                "Ответь строго в следующем формате (две строки):\n\n"
                "ОБЪЯСНЕНИЕ: <одно предложение — что именно ты изменяешь>\n"
                "ЗАМЕНА: <улучшенный вариант выделенного текста>\n\n"
                "Правила:\n"
                "- После слова ЗАМЕНА: — только новый текст, без кавычек и пояснений.\n"
                "- Не добавляй ничего после текста замены.\n"
                "- Сохраняй стиль юридического документа."
            )
            user_prompt = (
                f"ИНСТРУКЦИЯ: {question}\n\n"
                f"ВЫДЕЛЕННЫЙ ТЕКСТ:\n{selected_text}\n\n"
                f"=== КОНТЕКСТ ДОКУМЕНТА ===\n{doc_preview[:3000]}\n=== КОНЕЦ ==="
            )
            llm = create_legal_llm(temperature=0.3)
            response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
            answer = response.content if hasattr(response, "content") else str(response)

            explanation_match = re.search(r'ОБЪЯСНЕНИЕ:\s*(.+?)(?=\nЗАМЕНА:|$)', answer, re.DOTALL)
            replacement_match = re.search(r'ЗАМЕНА:\s*([\s\S]+)', answer)

            explanation = explanation_match.group(1).strip() if explanation_match else ""
            new_text = replacement_match.group(1).strip() if replacement_match else None

            if new_text:
                return {
                    "answer": explanation or "Правка подготовлена.",
                    "citations": [{"file": s.get("file", "Документ дела"), "file_id": s.get("file_id", "")} for s in sources[:3]],
                    "suggestions": ["Применить правку"],
                    "structured_edits": [{
                        "id": f"edit-{uuid.uuid4().hex[:8]}",
                        "original_text": selected_text,
                        "new_text": new_text,
                        "context_before": "",
                        "context_after": "",
                        "found_in_document": True,  # frontend uses exact range — always True
                    }],
                }
            else:
                # Fallback: show full LLM response as plain text
                clean_answer = re.sub(r'```[\s\S]*?```', '', answer, flags=re.DOTALL).strip()
                return {
                    "answer": clean_answer or "Не удалось подготовить правку. Попробуйте перефразировать запрос.",
                    "citations": [],
                    "suggestions": [],
                    "structured_edits": [],
                }
            # (unreachable — selected_text path always returns above)
        elif use_targeted:
            system_prompt = (
                "Ты — AI-ассистент для точечного редактирования юридических документов.\n\n"
                "Когда пользователь просит внести конкретные изменения:\n"
                "1. Кратко объясни что делаешь (1 предложение).\n"
                "2. Для КАЖДОГО изменения выведи блок:\n\n"
                "```edit\n"
                "НАЙТИ: точный текст из документа\n"
                "ЗАМЕНИТЬ: новый текст\n"
                "```\n\n"
                "ВАЖНО:\n"
                "- В НАЙТИ: пиши ТОЧНЫЙ текст из документа (не перефразируй).\n"
                "- Если нужно заменить имя, фамилию или короткое слово — в НАЙТИ указывай ТОЛЬКО само слово/фамилию, без окружающего контекста. Это позволит заменить все вхождения сразу.\n"
                "- В ЗАМЕНИТЬ: только новый текст, без пояснений.\n"
                "- Один блок — одно изменение.\n"
                "- Если текст не найден в документе — напиши об этом текстом."
            )
            if document_content:
                user_prompt = (
                    f"ЗАПРОС: {question}\n\n"
                    f"=== ДОКУМЕНТ ===\n{doc_preview}{doc_truncated}\n=== КОНЕЦ ===\n\n"
                    f"{other_docs_context}\n\n"
                    "Выведи точечные правки в формате ```edit."
                )
            else:
                user_prompt = (
                    f"ЗАПРОС: {question}\n\n{other_docs_context}\n\n"
                    "Документ не передан. Опиши изменения текстом."
                )
        else:
            system_prompt = (
                "Ты — AI-ассистент для редактирования юридических документов.\n\n"
                "1. Кратко объясни что изменил (1–2 предложения).\n"
                "2. Верни ПОЛНЫЙ обновлённый документ как HTML в блоке ```html\n\n"
                "ВАЖНО:\n"
                "- В блоке ```html должен быть ПОЛНЫЙ текст документа.\n"
                "- Используй теги: h1, h2, h3, p, ul, li, strong, em, table.\n"
                "- НЕ добавляй DOCTYPE, html, head, body.\n"
                "- Применяй профессиональные юридические формулировки."
            )
            if document_content:
                user_prompt = (
                    f"ЗАПРОС: {question}\n\n"
                    f"=== ДОКУМЕНТ (HTML) ===\n{doc_preview}{doc_truncated}\n=== КОНЕЦ ===\n\n"
                    f"{other_docs_context}\n\n"
                    "Внеси изменения. Объясни кратко что изменил, затем верни ПОЛНЫЙ HTML в блоке ```html."
                )
            else:
                user_prompt = (
                    f"ЗАПРОС: {question}\n\n{other_docs_context}\n\n"
                    "Документ пустой. Создай документ с нуля и верни ПОЛНЫЙ HTML в блоке ```html."
                )

        llm = create_legal_llm(temperature=0.3)
        response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        answer = response.content if hasattr(response, "content") else str(response)

        edited_content = None
        suggestions: List[str] = []
        structured_edits: List[Dict[str, Any]] = []

        def _count_occurrences(text: str) -> int:
            """Count how many times text appears in the document (HTML + plain)."""
            if not text or not document_content:
                return 0
            doc_plain = re.sub(r'<[^>]+>', '', document_content)
            return max(document_content.count(text), doc_plain.count(text))

        if use_targeted:
            edit_block_pattern = r'```edit\s*\n([\s\S]*?)```'
            for block_match in re.finditer(edit_block_pattern, answer, re.DOTALL | re.IGNORECASE):
                block = block_match.group(1).strip()
                find_match = re.search(r'НАЙТИ:\s*([\s\S]*?)(?=\nЗАМЕНИТЬ:)', block, re.IGNORECASE)
                replace_match = re.search(r'ЗАМЕНИТЬ:\s*([\s\S]*?)$', block, re.IGNORECASE)
                if find_match and replace_match:
                    original_text = find_match.group(1).strip().strip('"\'')
                    new_text = replace_match.group(1).strip().strip('"\'')
                    if original_text and new_text:
                        doc_plain = re.sub(r'<[^>]+>', '', document_content) if document_content else ""
                        found_in_doc = original_text in (document_content or "") or original_text in doc_plain
                        occurrences = _count_occurrences(original_text)
                        structured_edits.append({
                            "id": f"edit-{uuid.uuid4().hex[:8]}",
                            "original_text": original_text,
                            "new_text": new_text,
                            "context_before": "",
                            "context_after": "",
                            "found_in_document": found_in_doc,
                            "replace_all": occurrences > 1,
                        })

            # Fallback: LLM skipped code fences — parse raw НАЙТИ/ЗАМЕНИТЬ
            if not structured_edits:
                raw_match = re.search(
                    r'НАЙТИ:\s*"?([\s\S]*?)"?\s*\nЗАМЕНИТЬ:\s*"?([\s\S]+?)"?\s*(?=\n\S|\Z)',
                    answer, re.IGNORECASE
                )
                if raw_match:
                    original_text = raw_match.group(1).strip()
                    new_text = raw_match.group(2).strip()
                    if original_text and new_text:
                        doc_plain = re.sub(r'<[^>]+>', '', document_content) if document_content else ""
                        found_in_doc = original_text in (document_content or "") or original_text in doc_plain
                        occurrences = _count_occurrences(original_text)
                        structured_edits.append({
                            "id": f"edit-{uuid.uuid4().hex[:8]}",
                            "original_text": original_text,
                            "new_text": new_text,
                            "context_before": "",
                            "context_after": "",
                            "found_in_document": found_in_doc,
                            "replace_all": occurrences > 1,
                        })

            # Strip all edit-format content from answer text
            answer = re.sub(r'```edit[\s\S]*?```', '', answer, flags=re.DOTALL)
            answer = re.sub(r'\n*НАЙТИ:[\s\S]*', '', answer, flags=re.IGNORECASE)
            answer = re.sub(r'(?im)^\s*edit\s*$', '', answer)
            answer = re.sub(r'(?m)^\s*$\n', '', answer).strip()
            if structured_edits and not answer:
                answer = f"Предлагаю {len(structured_edits)} правку(-и). Примите или отклоните каждую."
            elif not answer:
                answer = "Не удалось найти подходящие фрагменты для замены."
            if structured_edits:
                suggestions.append("Применить все правки")
                logger.info(f"[DocumentAI] Found {len(structured_edits)} structured edits")
        else:
            html_patterns = [
                r'```html\s*\n([\s\S]*?)\n?```',
                r'```\s*\n\.?html\s*\n([\s\S]*?)\n?```',
                r'```[a-z.]*\n((?:\s*<[^>]+>[\s\S]*?))\n?```',
            ]
            for pattern in html_patterns:
                m = re.search(pattern, answer, re.DOTALL | re.IGNORECASE)
                if m:
                    extracted = m.group(1).strip()
                    lines = extracted.splitlines()
                    while lines and not lines[0].strip().startswith('<'):
                        lines.pop(0)
                    extracted = '\n'.join(lines).strip()
                    if extracted:
                        edited_content = extracted
                        suggestions.append("Применить изменения")
                        logger.info(f"[DocumentAI] Extracted HTML edit ({len(extracted)} chars)")
                    break

            answer = re.sub(r'```[\s\S]*?```', '', answer, flags=re.DOTALL).strip()
            answer = re.sub(r'(?m)^\s*\.?html\s*$', '', answer).strip()
            if not answer:
                answer = "Изменения готовы. Нажмите «Применить изменения» чтобы обновить документ."

        result = {
            "answer": answer,
            "citations": [{"file": s.get("file", "Документ дела"), "file_id": s.get("file_id", "")} for s in sources[:3]],
            "suggestions": suggestions,
            "structured_edits": structured_edits,
        }
        if edited_content:
            result["edited_content"] = edited_content
        return result

