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
        system_prompt = """Ты - опытный AI-ассистент для редактирования юридических документов.

ТВОИ ВОЗМОЖНОСТИ:
1. ВИДЕТЬ и АНАЛИЗИРОВАТЬ весь документ, открытый в редакторе
2. ОТВЕЧАТЬ на любые вопросы по документу  
3. РЕДАКТИРОВАТЬ документ по просьбе пользователя (даже без выделения текста!)
4. ИСПОЛЬЗОВАТЬ информацию из других документов дела для контекста
5. Анализировать документ на предмет рисков и противоречий

ПРАВИЛА РЕДАКТИРОВАНИЯ:
- Если пользователь просит изменить/улучшить/добавить/удалить что-то - СДЕЛАЙ ЭТО
- Выделенный текст НЕ обязателен - ты видишь весь документ и можешь найти нужное место
- После объяснения изменений ОБЯЗАТЕЛЬНО добавь готовый HTML код в блоке:
```html
<полный исправленный HTML код документа>
```

ВАЖНО:
- HTML должен быть ПОЛНЫМ и ВАЛИДНЫМ
- Сохраняй структуру и форматирование оригинала
- Вноси ТОЛЬКО те изменения, которые просит пользователь"""
        
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
        
        if is_edit_request:
            # Try to extract HTML from code blocks
            import re
            html_match = re.search(r'```(?:html)?\s*\n(.*?)\n```', answer, re.DOTALL)
            if html_match:
                edited_content = html_match.group(1).strip()
                suggestions.append("Применить изменения")
            else:
                # Try to find HTML tags in the answer
                html_tag_match = re.search(r'<[^>]+>.*?</[^>]+>', answer, re.DOTALL)
                if html_tag_match:
                    edited_content = html_tag_match.group(0)
                    suggestions.append("Применить изменения")
        
        result = {
            "answer": answer,
            "citations": [{"file": s.get("file", "Документ дела"), "file_id": s.get("file_id", "")} for s in sources[:3]],
            "suggestions": suggestions
        }
        
        # Add edited content if found
        if edited_content:
            result["edited_content"] = edited_content
        
        return result

