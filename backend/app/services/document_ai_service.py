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
            from app.services.langchain_agents.template_graph import create_template_graph
            from app.services.langchain_agents.template_state import TemplateState
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
            Dictionary with risk analysis and suggestions
        """
        if not text:
            return {
                "result": "Нет текста для проверки",
                "suggestions": []
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
        
        # Create LLM prompt
        system_prompt = """Ты - опытный юрист-аналитик, специализирующийся на выявлении юридических рисков.
Проанализируй предоставленный текст на предмет потенциальных юридических рисков, противоречий и проблемных формулировок.
Укажи конкретные места и предложи улучшения."""
        
        context_for_comparison = f'Контекст дела для сравнения:\n{context}' if context else ''
        user_prompt = f"""Проанализируй следующий текст на юридические риски:

{text}

{context_for_comparison}

Найди:
1. Потенциальные юридические риски
2. Противоречия и неясности
3. Проблемные формулировки
4. Отсутствующие важные пункты

Предложи конкретные улучшения для каждого найденного риска."""
        
        # Generate risk analysis
        llm = create_legal_llm(temperature=0.1)  # Low temperature for accuracy
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        result = response.content if hasattr(response, 'content') else str(response)
        
        return {
            "result": result,
            "suggestions": [
                "Исправить найденные риски",
                "Улучшить формулировки",
                "Добавить защитные пункты"
            ]
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
Сохрани смысл, но улучши формулировки, структуру и читаемость."""
        
        user_prompt = f"""Улучши следующий текст:

{text}

Сделай его более {style_descriptions.get(style, 'профессиональным')} и юридически корректным."""
        
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
Перепиши текст согласно инструкции пользователя, сохранив юридическую корректность и смысл."""
        
        user_prompt = f"""Перепиши следующий текст:

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
Замени сложные юридические термины на более простые, где это возможно без потери смысла."""
        
        user_prompt = f"""Упрости следующий юридический текст для понимания неспециалистом:

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
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Chat over document - ask questions and get AI to edit the document
        
        Args:
            document_id: Document identifier
            document_content: Current document content
            case_id: Case identifier for context
            question: User question/instruction
            user_id: User identifier (optional, for template caching)
            
        Returns:
            Dictionary with answer and suggested edits
        """
        # Проверяем, является ли запрос запросом на создание документа из шаблона
        create_keywords = [
            "создай договор", "составь договор", "нужен договор",
            "создай документ", "составь документ",
            "шаблон договора", "форма договора",
            "создай", "составь", "нужен шаблон"
        ]
        is_create_request = any(keyword in question.lower() for keyword in create_keywords)
        
        # Если это запрос на создание документа из шаблона
        if is_create_request:
            try:
                from app.services.langchain_agents.template_graph import create_template_graph
                from app.services.langchain_agents.template_state import TemplateState
                from app.services.document_editor_service import DocumentEditorService
                
                # Создаем граф для работы с шаблонами
                graph = create_template_graph(self.db)
                
                # Инициализируем состояние для графа
                initial_state: TemplateState = {
                    "user_query": question,
                    "case_id": case_id,
                    "user_id": user_id or "",
                    "cached_template": None,
                    "garant_template": None,
                    "template_source": None,
                    "final_template": None,
                    "adapted_content": None,
                    "document_id": document_id,  # Обновляем существующий документ или создаем новый
                    "messages": [],
                    "errors": [],
                    "metadata": {},
                    "should_adapt": True,
                    "document_title": None
                }
                
                # Запускаем граф
                logger.info(f"[DocumentAIService] Running template graph for document creation: {question[:100]}...")
                result = await graph.ainvoke(initial_state)
                
                if result.get("errors"):
                    error_msg = "; ".join(result["errors"])
                    logger.error(f"[DocumentAIService] Template graph errors: {error_msg}")
                    return {
                        "answer": f"Ошибка при создании документа из шаблона: {error_msg}",
                        "citations": [],
                        "suggestions": []
                    }
                
                # Если создан новый документ
                new_document_id = result.get("document_id")
                if new_document_id and new_document_id != document_id:
                    return {
                        "answer": f"Документ успешно создан из шаблона (источник: {result.get('template_source', 'unknown')}). Документ готов к редактированию.",
                        "citations": [],
                        "suggestions": ["Открыть документ", "Проверить на риски"],
                        "edited_content": result.get("adapted_content"),
                        "new_document_id": new_document_id
                    }
                
                return {
                    "answer": f"Документ обновлен из шаблона (источник: {result.get('template_source', 'unknown')}).",
                    "citations": [],
                    "suggestions": ["Проверить на риски", "Улучшить формулировки"],
                    "edited_content": result.get("adapted_content")
                }
            except Exception as template_error:
                logger.error(f"[DocumentAIService] Error using template graph: {template_error}", exc_info=True)
                # Fallback на обычный чат если template_graph не работает
        
        # Get context from case documents
        context = ""
        sources = []
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
            context = ""
            sources = []
        
        # Check if user wants to edit the document
        is_edit_request = any(keyword in question.lower() for keyword in [
            "изменить", "редактировать", "исправить", "добавить", "удалить", 
            "переписать", "улучшить", "изменить текст", "заменить"
        ])
        
        # Create LLM prompt for document editing
        system_prompt = """Ты - AI-ассистент для редактирования юридических документов.

ТВОИ ЗАДАЧИ:
1. Отвечать на вопросы о документе
2. Вносить точечные правки по запросу пользователя

ФОРМАТ ОТВЕТА ПРИ РЕДАКТИРОВАНИИ:
1. Сначала объясни какие изменения нужно внести
2. Затем укажи ТОЧНУЮ команду замены в формате:

```edit
НАЙТИ: <точный текст который нужно найти в документе>
ЗАМЕНИТЬ: <новый текст на замену>
```

ПРИМЕР:
Пользователь: "Добавь номер договора 123/2024 в пункт 1.1"
Ответ: "Добавляю номер договора в пункт 1.1.
```edit
НАЙТИ: 1.1. Предмет договора
ЗАМЕНИТЬ: 1.1. Договор №123/2024. Предмет договора
```"

ВАЖНО:
- В НАЙТИ указывай ТОЧНЫЙ текст из документа (можно короткий уникальный фрагмент)
- В ЗАМЕНИТЬ указывай полный новый текст
- Если нужно несколько замен - используй несколько блоков ```edit```
- Если пользователь просто задаёт вопрос - просто ответь без блока edit"""
        
        # Увеличиваем лимит до 15000 символов для полноценной работы с документом
        doc_limit = 15000
        doc_preview = document_content[:doc_limit] if document_content else ""
        doc_truncated = f"\n[... документ обрезан, показано {doc_limit} из {len(document_content)} символов ...]" if document_content and len(document_content) > doc_limit else ""
        
        # Формируем контекст из других документов дела
        other_docs_context = f'=== КОНТЕКСТ ИЗ ДРУГИХ ДОКУМЕНТОВ ДЕЛА ===\n{context}\n=== КОНЕЦ КОНТЕКСТА ===' if context else ''
        
        user_prompt = f"""ВОПРОС/ЗАПРОС ПОЛЬЗОВАТЕЛЯ: {question}

=== ПОЛНЫЙ ТЕКСТ ДОКУМЕНТА В РЕДАКТОРЕ ===
{doc_preview}{doc_truncated}
=== КОНЕЦ ДОКУМЕНТА ===

{other_docs_context}

Ответь на вопрос. Если требуется редактирование - предоставь полный обновленный HTML в блоке ```html ... ```"""
        
        llm = create_legal_llm(temperature=0.3)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        answer = response.content if hasattr(response, 'content') else str(response)
        
        # Try to extract edited HTML from answer
        edited_content = None
        suggestions = []
        
        # Список структурированных изменений для UI
        structured_edits = []
        
        if is_edit_request and document_content:
            import re
            import uuid
            # Новый подход: извлекаем команды НАЙТИ/ЗАМЕНИТЬ и применяем к оригиналу
            edit_blocks = re.findall(r'```edit\s*\n(.*?)\n```', answer, re.DOTALL)
            
            if edit_blocks:
                modified_content = document_content
                changes_applied = 0
                
                for block in edit_blocks:
                    # Парсим НАЙТИ и ЗАМЕНИТЬ
                    find_match = re.search(r'НАЙТИ:\s*(.+?)(?=\nЗАМЕНИТЬ:|$)', block, re.DOTALL)
                    replace_match = re.search(r'ЗАМЕНИТЬ:\s*(.+?)$', block, re.DOTALL)
                    
                    if find_match and replace_match:
                        find_text = find_match.group(1).strip()
                        replace_text = replace_match.group(1).strip()
                        
                        # Извлекаем контекст (до 50 символов до и после)
                        context_before = ""
                        context_after = ""
                        find_pos = document_content.find(find_text)
                        if find_pos != -1:
                            # Контекст до
                            start_ctx = max(0, find_pos - 50)
                            context_before = document_content[start_ctx:find_pos]
                            # Убираем незавершенные слова в начале
                            if start_ctx > 0:
                                space_pos = context_before.find(' ')
                                if space_pos != -1:
                                    context_before = context_before[space_pos + 1:]
                            
                            # Контекст после
                            end_pos = find_pos + len(find_text)
                            end_ctx = min(len(document_content), end_pos + 50)
                            context_after = document_content[end_pos:end_ctx]
                            # Убираем незавершенные слова в конце
                            if end_ctx < len(document_content):
                                space_pos = context_after.rfind(' ')
                                if space_pos != -1:
                                    context_after = context_after[:space_pos]
                        
                        # Добавляем структурированное изменение
                        structured_edits.append({
                            "id": f"edit-{uuid.uuid4().hex[:8]}",
                            "original_text": find_text,
                            "new_text": replace_text,
                            "context_before": context_before,
                            "context_after": context_after,
                            "found_in_document": find_text in modified_content
                        })
                        
                        if find_text in modified_content:
                            modified_content = modified_content.replace(find_text, replace_text, 1)
                            changes_applied += 1
                            logger.info(f"[DocumentAI] Applied edit: '{find_text[:50]}...' -> '{replace_text[:50]}...'")
                        else:
                            logger.warning(f"[DocumentAI] Text not found in document: '{find_text[:100]}...'")
                
                if changes_applied > 0:
                    edited_content = modified_content
                    suggestions.append("Применить изменения")
                    logger.info(f"[DocumentAI] Applied {changes_applied} edits to document")
                else:
                    answer += "\n\n⚠️ Не удалось найти указанный текст в документе. Попробуйте указать точную фразу из документа."
            else:
                # Fallback: старый подход с полным HTML (если ИИ вернул его)
                html_match = re.search(r'```(?:html)?\s*\n(.*?)\n```', answer, re.DOTALL)
                if html_match:
                    extracted_html = html_match.group(1).strip()
                    original_len = len(document_content)
                    # Принимаем только если HTML близок по размеру к оригиналу (±30%)
                    if original_len * 0.7 <= len(extracted_html) <= original_len * 1.5:
                        edited_content = extracted_html
                        suggestions.append("Применить изменения")
                        logger.info(f"[DocumentAI] Using full HTML fallback ({len(extracted_html)} chars)")
                    else:
                        logger.warning(f"[DocumentAI] HTML size mismatch, not applying")
        
        result = {
            "answer": answer,
            "citations": [{"file": s.get("file", "Документ дела"), "file_id": s.get("file_id", "")} for s in sources[:3]],
            "suggestions": suggestions,
            "structured_edits": structured_edits
        }
        
        # Add edited content if found and validated (для обратной совместимости)
        if edited_content:
            result["edited_content"] = edited_content
        
        return result

