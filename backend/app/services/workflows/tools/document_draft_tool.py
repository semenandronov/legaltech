"""Document Draft Tool for Workflows - Full Implementation"""
import html as html_module
from typing import Dict, Any, List, Optional, Tuple
from app.services.workflows.tool_registry import BaseTool, ToolResult
from app.services.llm_factory import create_llm
from app.services.document_editor_service import DocumentEditorService
from app.models.case import File, GlobalAssistantFile
from langchain_core.prompts import ChatPromptTemplate
import logging
import json
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


def _plain_text_to_editor_html(text: str) -> str:
    """Текст черновика → безопасный HTML для юридического редактора."""
    raw = (text or "").replace("\r\n", "\n")
    parts = [p.strip() for p in raw.split("\n") if p.strip()]
    if not parts:
        body = f"<p>{html_module.escape(raw[:100_000])}</p>"
    else:
        body = "\n".join(f"<p>{html_module.escape(p)}</p>" for p in parts)
    return f'<div class="workflow-draft legal-doc">{body}</div>'


# Шаблоны для разных типов документов
DOCUMENT_TEMPLATES = {
    "contract": {
        "name": "Договор",
        "sections": ["Преамбула", "Предмет договора", "Права и обязанности сторон", 
                    "Цена и порядок расчётов", "Ответственность сторон", 
                    "Срок действия", "Заключительные положения", "Реквизиты сторон"]
    },
    "claim": {
        "name": "Исковое заявление",
        "sections": ["Наименование суда", "Истец", "Ответчик", "Цена иска",
                    "Обстоятельства дела", "Правовое обоснование", "Просительная часть",
                    "Приложения"]
    },
    "letter": {
        "name": "Деловое письмо",
        "sections": ["Адресат", "Тема", "Вступление", "Основная часть", 
                    "Заключение", "Подпись"]
    },
    "memo": {
        "name": "Служебная записка",
        "sections": ["Адресат", "От кого", "Тема", "Содержание", "Предложения"]
    },
    "power_of_attorney": {
        "name": "Доверенность",
        "sections": ["Доверитель", "Представитель", "Полномочия", 
                    "Срок действия", "Право передоверия"]
    },
    "agreement": {
        "name": "Соглашение",
        "sections": ["Стороны", "Предмет соглашения", "Условия", 
                    "Ответственность", "Заключительные положения"]
    },
    "protocol": {
        "name": "Протокол",
        "sections": ["Дата и место", "Присутствующие", "Повестка дня",
                    "Слушали", "Решили", "Подписи"]
    },
    "act": {
        "name": "Акт",
        "sections": ["Наименование", "Дата составления", "Комиссия",
                    "Установлено", "Заключение", "Подписи"]
    }
}


DRAFT_PROMPT = """Ты - опытный юрист, специализирующийся на составлении юридических документов.
Создай профессиональный юридический документ на русском языке.

ТИП ДОКУМЕНТА: {document_type} ({document_type_name})

ОБЯЗАТЕЛЬНЫЕ РАЗДЕЛЫ:
{sections}

ВХОДНЫЕ ДАННЫЕ ДЛЯ ДОКУМЕНТА:
{variables}

КОНТЕКСТ ИЗ ПРЕДЫДУЩИХ ШАГОВ (если есть):
{context_data}

ДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ:
{instructions}

ТРЕБОВАНИЯ:
1. Используй официальный юридический стиль
2. Включи все обязательные разделы
3. Используй корректную юридическую терминологию
4. Добавь необходимые ссылки на законодательство где уместно
5. Структурируй документ с нумерацией пунктов
6. Включи места для подписей и дат где необходимо

Создай полный текст документа:"""


class DocumentDraftTool(BaseTool):
    """
    Tool for creating professional legal document drafts.
    
    Generates draft documents based on:
    - Document type templates
    - Input variables
    - Context from previous workflow steps
    - Custom instructions
    """
    
    name = "document_draft"
    display_name = "Document Draft"
    description = "Создание черновика юридического документа (договор, иск, письмо, доверенность)"
    
    def __init__(self, db):
        super().__init__(db)
        self.llm = None
        try:
            # Use use_rate_limiting=False for LangChain | operator compatibility
            self.llm = create_llm(temperature=0.3, use_rate_limiting=False)
            logger.info("DocumentDraftTool: LLM initialized")
        except Exception as e:
            logger.warning(f"DocumentDraftTool: Failed to initialize LLM: {e}")
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        doc_type = params.get("document_type")
        if not doc_type:
            errors.append("Требуется document_type")
        elif doc_type not in DOCUMENT_TEMPLATES and doc_type != "custom":
            errors.append(f"Неизвестный тип документа: {doc_type}. "
                         f"Доступные: {', '.join(DOCUMENT_TEMPLATES.keys())}, custom")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute document draft creation
        
        Params:
            document_type: Type of document (contract, claim, letter, memo, etc.)
            variables: Variables to fill in the template (dict)
            instructions: Additional instructions for the document
            title: Optional document title
            save_to_case: Whether to save the draft to the case (default: True)
            
        Context:
            user_id: User ID
            case_id: Case ID
            previous_results: Results from previous workflow steps
        """
        try:
            if not self.llm:
                return ToolResult(
                    success=False,
                    error="LLM not initialized - cannot generate document"
                )
            
            document_type = params.get("document_type", "contract")
            variables = params.get("variables", {})
            instructions = params.get("instructions", "")
            title = params.get("title")
            save_to_case = params.get("save_to_case", True)
            
            user_id = context.get("user_id")
            case_id = context.get("case_id")
            previous_results = context.get("previous_results", {})
            
            # Get template info
            template = DOCUMENT_TEMPLATES.get(document_type, {
                "name": "Документ",
                "sections": ["Введение", "Основная часть", "Заключение"]
            })
            
            # Format variables
            if isinstance(variables, dict):
                variables_str = json.dumps(variables, ensure_ascii=False, indent=2)
            else:
                variables_str = str(variables) if variables else "Не указаны"
            
            # Format context data from previous steps
            context_data = ""
            if previous_results:
                context_parts = []
                for step_id, result in previous_results.items():
                    if isinstance(result, dict):
                        # Extract useful info from previous results
                        if "summary" in result:
                            context_parts.append(f"[{step_id}] Резюме: {result['summary']}")
                        if "entities" in result:
                            context_parts.append(f"[{step_id}] Извлечённые сущности: {json.dumps(result['entities'][:5], ensure_ascii=False)}")
                        if "results" in result and isinstance(result["results"], list):
                            context_parts.append(f"[{step_id}] Найдено результатов: {len(result['results'])}")
                context_data = "\n".join(context_parts) if context_parts else "Нет данных из предыдущих шагов"
            else:
                context_data = "Нет данных из предыдущих шагов"
            
            # Format sections
            sections_str = "\n".join(f"- {section}" for section in template["sections"])
            
            # Create prompt and execute
            prompt = ChatPromptTemplate.from_template(DRAFT_PROMPT)
            chain = prompt | self.llm
            
            response = await chain.ainvoke({
                "document_type": document_type,
                "document_type_name": template["name"],
                "sections": sections_str,
                "variables": variables_str,
                "context_data": context_data,
                "instructions": instructions or "Следуй стандартному формату"
            })
            
            draft_content = response.content
            
            # Generate title if not provided
            if not title:
                title = f"{template['name']} - черновик от {datetime.now().strftime('%d.%m.%Y')}"
            
            # Save output: to case file (if case_id exists) or to global assistant storage.
            saved_file_id = None
            editor_document_id = None
            saved_global_file_id = None
            if save_to_case and case_id and user_id:
                try:
                    saved_file_id, editor_document_id = await self._save_draft_to_case(
                        content=draft_content,
                        title=title,
                        document_type=document_type,
                        case_id=case_id,
                        user_id=user_id
                    )
                except Exception as e:
                    logger.warning(f"Failed to save draft to case: {e}")
            elif save_to_case and user_id:
                try:
                    saved_global_file_id = await self._save_draft_to_global_assistant(
                        content=draft_content,
                        title=title,
                        document_type=document_type,
                        user_id=user_id
                    )
                except Exception as e:
                    logger.warning(f"Failed to save draft to global assistant files: {e}")
            
            # Calculate statistics
            word_count = len(draft_content.split())
            char_count = len(draft_content)

            artifact_dict: Dict[str, Any] = {
                "type": "document_draft",
                "id": saved_file_id or saved_global_file_id or str(uuid.uuid4()),
                "title": title,
                "document_type": document_type,
                "word_count": word_count,
                "storage": "case" if saved_file_id else ("global_assistant" if saved_global_file_id else "memory"),
            }
            if editor_document_id:
                artifact_dict["document_id"] = editor_document_id

            return ToolResult(
                success=True,
                data={
                    "document_type": document_type,
                    "document_type_name": template["name"],
                    "title": title,
                    "draft_content": draft_content,
                    "word_count": word_count,
                    "char_count": char_count,
                    "sections_included": template["sections"],
                    "saved_file_id": saved_file_id,
                    "editor_document_id": editor_document_id,
                    "saved_global_file_id": saved_global_file_id
                },
                output_summary=f"Создан черновик '{title}' ({template['name']}): {word_count} слов, "
                              f"{len(template['sections'])} разделов" + 
                              (
                                  f". Сохранён в дело."
                                  if saved_file_id
                                  else (f". Сохранён в глобальные файлы ассистента." if saved_global_file_id else "")
                              ),
                artifacts=[artifact_dict],
                llm_calls=1
            )
            
        except Exception as e:
            logger.error(f"DocumentDraftTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )
    
    async def _save_draft_to_case(
        self,
        content: str,
        title: str,
        document_type: str,
        case_id: str,
        user_id: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Save draft as case File and mirror into Document Editor so it appears in /editor.

        Returns:
            (case_file_id, editor_document_id or None)
        """
        try:
            file_id = str(uuid.uuid4())
            safe_title = (title or "Черновик").strip()
            if not safe_title.lower().endswith(".txt"):
                filename = f"{safe_title}.txt"
            else:
                filename = safe_title
            display_title = filename[:-4] if filename.lower().endswith(".txt") else filename

            file = File(
                id=file_id,
                case_id=case_id,
                filename=filename,
                file_type="text/plain",
                original_text=content,
                processing_status="ready",
            )

            self.db.add(file)
            self.db.commit()

            logger.info(f"Saved draft document to case {case_id}: {file_id}")

            editor_document_id: Optional[str] = None
            try:
                doc_service = DocumentEditorService(self.db)
                html_content = _plain_text_to_editor_html(content)
                editor_doc = doc_service.create_document(
                    case_id=case_id,
                    user_id=user_id,
                    title=display_title,
                    content=html_content,
                    metadata={
                        "source": "workflow_document_draft",
                        "source_case_file_id": file_id,
                        "document_type": document_type,
                    },
                )
                editor_document_id = str(editor_doc.id)
                logger.info(
                    "Mirrored workflow draft to editor document %s (case file %s)",
                    editor_document_id,
                    file_id,
                )
            except Exception as edoc_exc:
                logger.warning(
                    "Could not create editor Document for workflow draft (file %s): %s",
                    file_id,
                    edoc_exc,
                    exc_info=True,
                )

            return file_id, editor_document_id

        except Exception as e:
            logger.error(f"Failed to save draft: {e}")
            self.db.rollback()
            return None, None

    async def _save_draft_to_global_assistant(
        self,
        content: str,
        title: str,
        document_type: str,
        user_id: str
    ) -> Optional[str]:
        """Save draft document into global assistant file storage."""
        try:
            file_id = str(uuid.uuid4())
            file = GlobalAssistantFile(
                id=file_id,
                user_id=user_id,
                filename=f"{title}.txt",
                file_type=document_type or "txt",
                original_text=content,
                file_content=content.encode("utf-8"),
            )
            self.db.add(file)
            self.db.commit()
            logger.info("Saved draft document to global assistant files: %s", file_id)
            return file_id
        except Exception as e:
            logger.error(f"Failed to save draft to global assistant files: {e}")
            self.db.rollback()
            return None
