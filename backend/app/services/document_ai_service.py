"""Document AI Service for Legal AI Vault"""
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.llm_factory import create_legal_llm
from app.services.document_processor import DocumentProcessor
from langchain_core.messages import HumanMessage, SystemMessage
import logging

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
    
    def generate_contract(
        self,
        prompt: str,
        case_id: str
    ) -> Dict[str, Any]:
        """
        Generate a contract based on prompt and case context
        
        Args:
            prompt: Description of contract to generate
            case_id: Case identifier for context
            
        Returns:
            Dictionary with generated contract text
        """
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
        
        user_prompt = f"""Запрос: {prompt}

{f'Контекст дела:\n{context}' if context else ''}

Составь профессиональный юридический документ. Используй структуру с нумерацией пунктов, четкими формулировками и всеми необходимыми разделами."""
        
        # Generate contract
        llm = create_legal_llm(temperature=0.3)  # Slightly higher temperature for creativity
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
        
        user_prompt = f"""Проанализируй следующий текст на юридические риски:

{text}

{f'Контекст дела для сравнения:\n{context}' if context else ''}

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
        
        user_prompt = f"""Запрос пользователя: {prompt}

{f'Выделенный текст:\n{selected_text}' if selected_text else ''}

{f'Полное содержимое документа:\n{document_content[:2000]}' if document_content else ''}

{f'Контекст дела:\n{context}' if context else ''}

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

