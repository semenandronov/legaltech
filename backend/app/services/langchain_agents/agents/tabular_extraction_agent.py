"""
TabularExtractionAgent - агент для извлечения данных в таблицу.

Это агент (не узел), потому что:
1. Использует Map-Reduce паттерн для параллельной обработки документов
2. Имеет циклы (итерация по документам и ячейкам)
3. Поддерживает Human-in-the-Loop через LangGraph interrupt

Паттерн:
1. Валидация колонок
2. Map: извлечение данных из каждого документа параллельно
3. Reduce: объединение результатов
4. Проверка уверенности
5. HITL для низкой уверенности
6. Сохранение результатов
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from app.services.llm_factory import create_llm
from app.services.rag_service import RAGService
from sqlalchemy.orm import Session
import logging
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


@dataclass
class ExtractionColumn:
    """Определение колонки для извлечения."""
    id: str
    label: str
    column_type: str  # text, number, currency, yes_no, date, tag, verbatim
    prompt: str
    config: Optional[Dict[str, Any]] = None


@dataclass
class ExtractionResult:
    """Результат извлечения для одной ячейки."""
    column_id: str
    file_id: str
    value: str
    confidence: float  # 0.0 - 1.0
    source_quote: Optional[str] = None
    source_page: Optional[int] = None
    needs_clarification: bool = False
    clarification_question: Optional[str] = None


@dataclass
class TabularExtractionConfig:
    """Конфигурация агента извлечения."""
    review_id: str
    case_id: str
    user_id: str
    columns: List[ExtractionColumn]
    file_ids: List[str]
    confidence_threshold: float = 0.8  # Порог уверенности для HITL
    max_parallel_docs: int = 5
    enable_hitl: bool = True


class TabularExtractionAgent:
    """
    Агент для извлечения данных из документов в таблицу.
    
    Использует Map-Reduce паттерн:
    - Map: параллельное извлечение из каждого документа
    - Reduce: объединение и валидация результатов
    
    Поддерживает HITL для ячеек с низкой уверенностью.
    """
    
    def __init__(
        self,
        config: TabularExtractionConfig,
        db: Session,
        rag_service: RAGService = None
    ):
        """
        Инициализация агента.
        
        Args:
            config: Конфигурация извлечения
            db: Database session
            rag_service: RAG service для получения текста документов
        """
        self.config = config
        self.db = db
        self.rag_service = rag_service
        self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
        
        # Результаты извлечения
        self.results: List[ExtractionResult] = []
        self.pending_clarifications: List[ExtractionResult] = []
        
        logger.info(
            f"[TabularAgent] Initialized for review {config.review_id} "
            f"with {len(config.columns)} columns and {len(config.file_ids)} files"
        )
    
    def _get_document_text(self, file_id: str) -> Tuple[str, str]:
        """
        Получить текст документа.
        
        Returns:
            Tuple[filename, text]
        """
        from app.models.case import File
        
        file = self.db.query(File).filter(File.id == file_id).first()
        if not file:
            return "", ""
        
        text = file.original_text or ""
        return file.filename, text
    
    def _extract_cell_value(
        self,
        column: ExtractionColumn,
        document_text: str,
        filename: str
    ) -> ExtractionResult:
        """
        Извлечь значение для одной ячейки.
        
        Args:
            column: Определение колонки
            document_text: Текст документа
            filename: Имя файла
        
        Returns:
            Результат извлечения
        """
        # Формируем промпт на основе типа колонки
        type_instructions = {
            "text": "Извлеки текстовое значение.",
            "number": "Извлеки числовое значение. Верни только число.",
            "currency": "Извлеки денежную сумму. Формат: число с валютой (например, 100000 руб.).",
            "yes_no": "Ответь только 'Да' или 'Нет'.",
            "date": "Извлеки дату. Формат: ДД.ММ.ГГГГ.",
            "tag": "Выбери подходящий тег из списка.",
            "verbatim": "Процитируй точный текст из документа."
        }
        
        type_instruction = type_instructions.get(column.column_type, type_instructions["text"])
        
        # Дополнительные инструкции для tag
        tag_options = ""
        if column.column_type == "tag" and column.config:
            options = column.config.get("options", [])
            if options:
                tag_labels = [opt.get("label", opt) if isinstance(opt, dict) else opt for opt in options]
                tag_options = f"\nДоступные теги: {', '.join(tag_labels)}"
        
        prompt = f"""Извлеки информацию из документа.

ДОКУМЕНТ: {filename}
ТЕКСТ ДОКУМЕНТА:
{document_text[:8000]}

ЗАДАЧА: {column.prompt}
ТИП ДАННЫХ: {column.column_type}
{type_instruction}{tag_options}

Ответь в формате JSON:
{{
    "value": "извлечённое значение или null если не найдено",
    "confidence": 0.0-1.0,
    "source_quote": "цитата из документа, подтверждающая значение",
    "source_page": номер страницы или null
}}

Если информация не найдена, верни:
{{
    "value": null,
    "confidence": 0.0,
    "source_quote": null,
    "source_page": null
}}
"""
        
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Парсим JSON
            from app.services.langchain_agents.utils import extract_json_from_response
            result_json = extract_json_from_response(response_text)
            
            if result_json:
                value = result_json.get("value")
                confidence = float(result_json.get("confidence", 0.0))
                
                # Определяем, нужно ли уточнение
                needs_clarification = confidence < self.config.confidence_threshold and value is not None
                clarification_question = None
                
                if needs_clarification:
                    clarification_question = f"Уточните значение для '{column.label}' в документе '{filename}'. Найденное значение: '{value}' (уверенность: {confidence:.0%})"
                
                return ExtractionResult(
                    column_id=column.id,
                    file_id="",  # Будет заполнено позже
                    value=str(value) if value is not None else "",
                    confidence=confidence,
                    source_quote=result_json.get("source_quote"),
                    source_page=result_json.get("source_page"),
                    needs_clarification=needs_clarification,
                    clarification_question=clarification_question
                )
            else:
                return ExtractionResult(
                    column_id=column.id,
                    file_id="",
                    value="",
                    confidence=0.0,
                    needs_clarification=True,
                    clarification_question=f"Не удалось извлечь '{column.label}' из документа '{filename}'"
                )
                
        except Exception as e:
            logger.error(f"[TabularAgent] Error extracting {column.label}: {e}", exc_info=True)
            return ExtractionResult(
                column_id=column.id,
                file_id="",
                value="",
                confidence=0.0,
                needs_clarification=True,
                clarification_question=f"Ошибка извлечения '{column.label}': {str(e)}"
            )
    
    def _extract_from_document(self, file_id: str) -> List[ExtractionResult]:
        """
        Извлечь все значения из одного документа (Map операция).
        
        Args:
            file_id: ID файла
        
        Returns:
            Список результатов извлечения для всех колонок
        """
        filename, document_text = self._get_document_text(file_id)
        
        if not document_text:
            logger.warning(f"[TabularAgent] No text for file {file_id}")
            return [
                ExtractionResult(
                    column_id=col.id,
                    file_id=file_id,
                    value="",
                    confidence=0.0,
                    needs_clarification=True,
                    clarification_question=f"Документ '{filename}' пуст или не содержит текста"
                )
                for col in self.config.columns
            ]
        
        results = []
        for column in self.config.columns:
            result = self._extract_cell_value(column, document_text, filename)
            result.file_id = file_id
            results.append(result)
        
        logger.info(f"[TabularAgent] Extracted {len(results)} values from {filename}")
        return results
    
    async def extract_all(self) -> Dict[str, Any]:
        """
        Извлечь данные из всех документов (Map-Reduce).
        
        Returns:
            Словарь с результатами и запросами на уточнение
        """
        logger.info(f"[TabularAgent] Starting extraction for {len(self.config.file_ids)} documents")
        
        all_results = []
        
        # Map: параллельное извлечение из документов
        with ThreadPoolExecutor(max_workers=self.config.max_parallel_docs) as executor:
            futures = [
                executor.submit(self._extract_from_document, file_id)
                for file_id in self.config.file_ids
            ]
            
            for future in futures:
                try:
                    results = future.result(timeout=60)
                    all_results.extend(results)
                except Exception as e:
                    logger.error(f"[TabularAgent] Extraction error: {e}", exc_info=True)
        
        # Reduce: разделяем на успешные и требующие уточнения
        successful = []
        needs_clarification = []
        
        for result in all_results:
            if result.needs_clarification and self.config.enable_hitl:
                needs_clarification.append(result)
            else:
                successful.append(result)
        
        self.results = successful
        self.pending_clarifications = needs_clarification
        
        logger.info(
            f"[TabularAgent] Extraction complete: "
            f"{len(successful)} successful, {len(needs_clarification)} need clarification"
        )
        
        return {
            "successful": [self._result_to_dict(r) for r in successful],
            "needs_clarification": [self._result_to_dict(r) for r in needs_clarification],
            "total_cells": len(all_results),
            "success_rate": len(successful) / len(all_results) if all_results else 0
        }
    
    def _result_to_dict(self, result: ExtractionResult) -> Dict[str, Any]:
        """Конвертировать результат в словарь."""
        return {
            "column_id": result.column_id,
            "file_id": result.file_id,
            "value": result.value,
            "confidence": result.confidence,
            "source_quote": result.source_quote,
            "source_page": result.source_page,
            "needs_clarification": result.needs_clarification,
            "clarification_question": result.clarification_question
        }
    
    def get_clarification_requests(self) -> List[Dict[str, Any]]:
        """
        Получить запросы на уточнение для HITL.
        
        Returns:
            Список запросов на уточнение
        """
        return [
            {
                "request_id": f"{r.file_id}_{r.column_id}",
                "column_id": r.column_id,
                "file_id": r.file_id,
                "question": r.clarification_question,
                "current_value": r.value,
                "confidence": r.confidence
            }
            for r in self.pending_clarifications
        ]
    
    def apply_clarification(
        self,
        request_id: str,
        user_value: str,
        user_confirmed: bool = True
    ) -> bool:
        """
        Применить уточнение от пользователя.
        
        Args:
            request_id: ID запроса (file_id_column_id)
            user_value: Значение от пользователя
            user_confirmed: Пользователь подтвердил значение
        
        Returns:
            True если уточнение применено
        """
        for i, result in enumerate(self.pending_clarifications):
            if f"{result.file_id}_{result.column_id}" == request_id:
                if user_confirmed:
                    result.value = user_value
                    result.confidence = 1.0  # Подтверждено пользователем
                    result.needs_clarification = False
                    
                    # Перемещаем в успешные
                    self.results.append(result)
                    self.pending_clarifications.pop(i)
                    
                    logger.info(f"[TabularAgent] Clarification applied for {request_id}")
                    return True
                else:
                    # Пользователь отклонил - оставляем пустым
                    result.value = ""
                    result.confidence = 0.0
                    result.needs_clarification = False
                    
                    self.results.append(result)
                    self.pending_clarifications.pop(i)
                    
                    logger.info(f"[TabularAgent] Clarification rejected for {request_id}")
                    return True
        
        return False
    
    async def save_results(self) -> Dict[str, Any]:
        """
        Сохранить результаты в базу данных.
        
        Returns:
            Статистика сохранения
        """
        from app.services.tabular_review_service import TabularReviewService
        
        service = TabularReviewService(self.db)
        saved_count = 0
        errors = []
        
        for result in self.results:
            try:
                # Сохраняем ячейку
                service.update_cell(
                    review_id=self.config.review_id,
                    file_id=result.file_id,
                    column_id=result.column_id,
                    value=result.value,
                    user_id=self.config.user_id,
                    is_manual=False,
                    confidence=result.confidence,
                    source_quote=result.source_quote
                )
                saved_count += 1
            except Exception as e:
                logger.error(f"[TabularAgent] Error saving cell: {e}", exc_info=True)
                errors.append(str(e))
        
        logger.info(f"[TabularAgent] Saved {saved_count} cells, {len(errors)} errors")
        
        return {
            "saved_count": saved_count,
            "total_count": len(self.results),
            "errors": errors
        }



