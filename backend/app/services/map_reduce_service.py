"""
Map-Reduce Service для обработки документов любого масштаба.

Позволяет работать как с одним документом, так и с тысячами документов,
автоматически выбирая оптимальную стратегию обработки.

Стратегии:
1. DIRECT - прямой запрос к LLM (для малого объёма, <10 документов)
2. MAP_REDUCE - параллельная обработка с агрегацией (для среднего объёма, 10-100 документов)
3. HIERARCHICAL - иерархическая обработка (для большого объёма, >100 документов)

Примеры использования:
- "О чём документы?" -> MAP: извлечь суть из каждого -> REDUCE: объединить в обзор
- "Найди все суммы" -> MAP: найти суммы в каждом документе -> REDUCE: собрать в список
- "Сравни договоры" -> MAP: извлечь ключевые условия -> REDUCE: сравнить
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class ProcessingStrategy(Enum):
    """Стратегия обработки документов"""
    DIRECT = "direct"  # Прямой запрос (малый объём)
    MAP_REDUCE = "map_reduce"  # Map-Reduce (средний объём)
    HIERARCHICAL = "hierarchical"  # Иерархический (большой объём)


@dataclass
class MapResult:
    """Результат Map-фазы для одного документа"""
    source: str  # Имя файла/источник
    content: str  # Извлечённый контент
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


@dataclass
class ReduceResult:
    """Финальный результат после Reduce-фазы"""
    answer: str  # Финальный ответ
    sources: List[str]  # Список источников
    strategy_used: ProcessingStrategy  # Использованная стратегия
    documents_processed: int  # Количество обработанных документов
    metadata: Dict[str, Any] = field(default_factory=dict)


class MapReduceService:
    """
    Сервис Map-Reduce для обработки документов.
    
    Автоматически выбирает стратегию в зависимости от объёма данных:
    - <10 документов: DIRECT (прямой запрос)
    - 10-100 документов: MAP_REDUCE (параллельная обработка)
    - >100 документов: HIERARCHICAL (иерархическая обработка)
    """
    
    # Пороги для выбора стратегии
    DIRECT_THRESHOLD = 10  # До 10 документов - прямой запрос
    MAP_REDUCE_THRESHOLD = 100  # До 100 документов - Map-Reduce
    # Больше 100 - иерархический
    
    # Размеры батчей
    MAP_BATCH_SIZE = 5  # Сколько документов обрабатывать параллельно в Map
    REDUCE_BATCH_SIZE = 10  # Сколько результатов объединять за раз в Reduce
    
    # Лимиты контекста
    MAX_CHARS_PER_DOC = 3000  # Максимум символов на документ в Map
    MAX_CHARS_REDUCE = 8000  # Максимум символов для Reduce
    
    def __init__(self, llm=None):
        """
        Инициализация сервиса.
        
        Args:
            llm: LLM для обработки (если None - создаётся автоматически)
        """
        self.llm = llm
        self._ensure_llm()
    
    def _ensure_llm(self):
        """Создать LLM если не передан"""
        if self.llm is None:
            try:
                from app.services.llm_factory import create_legal_llm
                self.llm = create_legal_llm(timeout=60.0)
                logger.info("[MapReduce] Created LLM instance")
            except Exception as e:
                logger.error(f"[MapReduce] Failed to create LLM: {e}")
                raise
    
    def choose_strategy(self, num_documents: int) -> ProcessingStrategy:
        """
        Выбрать оптимальную стратегию обработки.
        
        Args:
            num_documents: Количество документов
            
        Returns:
            Оптимальная стратегия
        """
        if num_documents <= self.DIRECT_THRESHOLD:
            return ProcessingStrategy.DIRECT
        elif num_documents <= self.MAP_REDUCE_THRESHOLD:
            return ProcessingStrategy.MAP_REDUCE
        else:
            return ProcessingStrategy.HIERARCHICAL
    
    async def process(
        self,
        documents: List[Document],
        question: str,
        task_type: str = "answer"
    ) -> ReduceResult:
        """
        Обработать документы и ответить на вопрос.
        
        Args:
            documents: Список документов
            question: Вопрос пользователя
            task_type: Тип задачи:
                - "answer" - ответить на вопрос
                - "summarize" - суммаризация
                - "extract" - извлечение сущностей
                - "compare" - сравнение
                
        Returns:
            ReduceResult с ответом
        """
        if not documents:
            return ReduceResult(
                answer="Документы не найдены.",
                sources=[],
                strategy_used=ProcessingStrategy.DIRECT,
                documents_processed=0
            )
        
        strategy = self.choose_strategy(len(documents))
        logger.info(f"[MapReduce] Processing {len(documents)} documents with strategy: {strategy.value}")
        
        if strategy == ProcessingStrategy.DIRECT:
            return await self._process_direct(documents, question, task_type)
        elif strategy == ProcessingStrategy.MAP_REDUCE:
            return await self._process_map_reduce(documents, question, task_type)
        else:
            return await self._process_hierarchical(documents, question, task_type)
    
    async def _process_direct(
        self,
        documents: List[Document],
        question: str,
        task_type: str
    ) -> ReduceResult:
        """
        Прямая обработка (для малого объёма).
        Все документы отправляются в один запрос к LLM.
        """
        # Собираем контекст из всех документов
        context_parts = []
        sources = []
        total_chars = 0
        
        for doc in documents:
            source = doc.metadata.get("source_file", "Документ")
            content = doc.page_content[:self.MAX_CHARS_PER_DOC]
            
            if total_chars + len(content) > 20000:  # Лимит общего контекста
                content = content[:20000 - total_chars]
                context_parts.append(f"[{source}]:\n{content}...")
                sources.append(source)
                break
            
            context_parts.append(f"[{source}]:\n{content}")
            sources.append(source)
            total_chars += len(content)
        
        context = "\n\n".join(context_parts)
        
        # Генерируем ответ
        prompt = self._build_prompt(question, context, task_type)
        
        try:
            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            answer = response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"[MapReduce] Direct processing error: {e}")
            answer = f"Ошибка обработки: {str(e)}"
        
        return ReduceResult(
            answer=answer,
            sources=list(set(sources)),
            strategy_used=ProcessingStrategy.DIRECT,
            documents_processed=len(documents)
        )
    
    async def _process_map_reduce(
        self,
        documents: List[Document],
        question: str,
        task_type: str
    ) -> ReduceResult:
        """
        Map-Reduce обработка (для среднего объёма).
        
        1. MAP: Параллельно обрабатываем документы батчами
        2. REDUCE: Объединяем результаты в финальный ответ
        """
        # === MAP PHASE ===
        map_results = await self._map_phase(documents, question, task_type)
        
        # Фильтруем успешные результаты
        successful_results = [r for r in map_results if r.success and r.content]
        
        if not successful_results:
            return ReduceResult(
                answer="Не удалось извлечь информацию из документов.",
                sources=[],
                strategy_used=ProcessingStrategy.MAP_REDUCE,
                documents_processed=len(documents)
            )
        
        # === REDUCE PHASE ===
        answer = await self._reduce_phase(successful_results, question, task_type)
        
        sources = list(set(r.source for r in successful_results))
        
        return ReduceResult(
            answer=answer,
            sources=sources,
            strategy_used=ProcessingStrategy.MAP_REDUCE,
            documents_processed=len(documents),
            metadata={"map_results_count": len(successful_results)}
        )
    
    async def _process_hierarchical(
        self,
        documents: List[Document],
        question: str,
        task_type: str
    ) -> ReduceResult:
        """
        Иерархическая обработка (для большого объёма).
        
        1. Разбиваем документы на группы
        2. Map-Reduce для каждой группы
        3. Финальный Reduce по результатам групп
        """
        # Разбиваем на группы по 50 документов
        group_size = 50
        groups = [documents[i:i+group_size] for i in range(0, len(documents), group_size)]
        
        logger.info(f"[MapReduce] Hierarchical: {len(groups)} groups of ~{group_size} documents")
        
        # Обрабатываем каждую группу через Map-Reduce
        group_results = []
        for i, group in enumerate(groups):
            logger.info(f"[MapReduce] Processing group {i+1}/{len(groups)}")
            result = await self._process_map_reduce(group, question, task_type)
            group_results.append(MapResult(
                source=f"Группа {i+1} ({len(group)} документов)",
                content=result.answer,
                metadata={"sources": result.sources}
            ))
        
        # Финальный Reduce по результатам групп
        final_answer = await self._reduce_phase(group_results, question, task_type)
        
        # Собираем все источники
        all_sources = []
        for gr in group_results:
            all_sources.extend(gr.metadata.get("sources", []))
        
        return ReduceResult(
            answer=final_answer,
            sources=list(set(all_sources)),
            strategy_used=ProcessingStrategy.HIERARCHICAL,
            documents_processed=len(documents),
            metadata={"groups_processed": len(groups)}
        )
    
    async def _map_phase(
        self,
        documents: List[Document],
        question: str,
        task_type: str
    ) -> List[MapResult]:
        """
        Map-фаза: параллельная обработка документов.
        
        Извлекает релевантную информацию из каждого документа.
        """
        results = []
        
        # Обрабатываем батчами для контроля параллелизма
        for i in range(0, len(documents), self.MAP_BATCH_SIZE):
            batch = documents[i:i+self.MAP_BATCH_SIZE]
            
            # Параллельная обработка батча
            tasks = [
                self._map_single_document(doc, question, task_type)
                for doc in batch
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    results.append(MapResult(
                        source=batch[j].metadata.get("source_file", "Документ"),
                        content="",
                        success=False,
                        error=str(result)
                    ))
                else:
                    results.append(result)
        
        logger.info(f"[MapReduce] Map phase completed: {len(results)} documents processed")
        return results
    
    async def _map_single_document(
        self,
        document: Document,
        question: str,
        task_type: str
    ) -> MapResult:
        """Обработать один документ в Map-фазе"""
        source = document.metadata.get("source_file", "Документ")
        content = document.page_content[:self.MAX_CHARS_PER_DOC]
        
        # Промпт для извлечения релевантной информации
        if task_type == "summarize":
            map_prompt = f"""Кратко изложи основное содержание этого документа (2-3 предложения):

{content}

Краткое содержание:"""
        elif task_type == "extract":
            map_prompt = f"""Извлеки ключевые факты из документа (даты, суммы, имена, организации):

{content}

Ключевые факты:"""
        elif task_type == "compare":
            map_prompt = f"""Извлеки ключевые условия и характеристики из документа для сравнения:

{content}

Ключевые характеристики:"""
        else:  # answer
            map_prompt = f"""Вопрос: {question}

Документ:
{content}

Извлеки из документа информацию, релевантную вопросу. Если информации нет - напиши "Нет релевантной информации".

Релевантная информация:"""
        
        try:
            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=map_prompt)])
            extracted = response.content if hasattr(response, 'content') else str(response)
            
            # Проверяем что извлечено что-то полезное
            if "нет релевантной информации" in extracted.lower() or len(extracted.strip()) < 10:
                return MapResult(source=source, content="", success=True)
            
            return MapResult(source=source, content=extracted.strip())
            
        except Exception as e:
            logger.warning(f"[MapReduce] Map error for {source}: {e}")
            return MapResult(source=source, content="", success=False, error=str(e))
    
    async def _reduce_phase(
        self,
        map_results: List[MapResult],
        question: str,
        task_type: str
    ) -> str:
        """
        Reduce-фаза: объединение результатов Map в финальный ответ.
        """
        # Если результатов много - делаем итеративный Reduce
        if len(map_results) > self.REDUCE_BATCH_SIZE:
            return await self._iterative_reduce(map_results, question, task_type)
        
        # Собираем контекст из Map-результатов
        context_parts = []
        for result in map_results:
            if result.content:
                context_parts.append(f"[{result.source}]:\n{result.content}")
        
        context = "\n\n".join(context_parts)
        
        # Обрезаем если слишком длинный
        if len(context) > self.MAX_CHARS_REDUCE:
            context = context[:self.MAX_CHARS_REDUCE] + "..."
        
        # Промпт для финального ответа
        reduce_prompt = self._build_reduce_prompt(question, context, task_type, len(map_results))
        
        try:
            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=reduce_prompt)])
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"[MapReduce] Reduce error: {e}")
            return f"Ошибка объединения результатов: {str(e)}"
    
    async def _iterative_reduce(
        self,
        map_results: List[MapResult],
        question: str,
        task_type: str
    ) -> str:
        """
        Итеративный Reduce для большого количества результатов.
        Объединяем по батчам, пока не останется один результат.
        """
        current_results = map_results
        iteration = 0
        
        while len(current_results) > self.REDUCE_BATCH_SIZE:
            iteration += 1
            logger.info(f"[MapReduce] Iterative reduce iteration {iteration}: {len(current_results)} results")
            
            new_results = []
            for i in range(0, len(current_results), self.REDUCE_BATCH_SIZE):
                batch = current_results[i:i+self.REDUCE_BATCH_SIZE]
                
                # Объединяем батч
                combined = await self._reduce_phase(batch, question, task_type)
                new_results.append(MapResult(
                    source=f"Объединение {i//self.REDUCE_BATCH_SIZE + 1}",
                    content=combined
                ))
            
            current_results = new_results
        
        # Финальный Reduce
        return await self._reduce_phase(current_results, question, task_type)
    
    def _build_prompt(self, question: str, context: str, task_type: str) -> str:
        """Построить промпт для прямого запроса"""
        if task_type == "summarize":
            return f"""Сделай краткий обзор содержания документов:

{context}

Краткий обзор:"""
        elif task_type == "extract":
            return f"""Извлеки все ключевые факты из документов (даты, суммы, имена, организации):

{context}

Ключевые факты:"""
        elif task_type == "compare":
            return f"""Сравни документы, выдели сходства и различия:

{context}

Сравнительный анализ:"""
        else:  # answer
            return f"""На основе документов ответь на вопрос.

Документы:
{context}

Вопрос: {question}

Ответ (используй только информацию из документов, указывай источники):"""
    
    def _build_reduce_prompt(
        self,
        question: str,
        context: str,
        task_type: str,
        num_sources: int
    ) -> str:
        """Построить промпт для Reduce-фазы"""
        if task_type == "summarize":
            return f"""На основе извлечённой информации из {num_sources} документов составь общий обзор:

{context}

Общий обзор (кратко, структурированно):"""
        elif task_type == "extract":
            return f"""Объедини извлечённые факты из {num_sources} документов в структурированный список:

{context}

Структурированный список фактов:"""
        elif task_type == "compare":
            return f"""На основе характеристик из {num_sources} документов составь сравнительный анализ:

{context}

Сравнительный анализ:"""
        else:  # answer
            return f"""На основе информации из {num_sources} документов ответь на вопрос.

Извлечённая информация:
{context}

Вопрос: {question}

Финальный ответ (кратко, по существу, с указанием источников):"""


# === Удобные функции для использования в инструментах ===

async def map_reduce_answer(
    documents: List[Document],
    question: str,
    llm=None
) -> Tuple[str, List[str]]:
    """
    Ответить на вопрос по документам с использованием Map-Reduce.
    
    Args:
        documents: Список документов
        question: Вопрос
        llm: LLM (опционально)
        
    Returns:
        (ответ, список_источников)
    """
    service = MapReduceService(llm=llm)
    result = await service.process(documents, question, task_type="answer")
    return result.answer, result.sources


async def map_reduce_summarize(
    documents: List[Document],
    llm=None
) -> Tuple[str, List[str]]:
    """
    Суммаризация документов с использованием Map-Reduce.
    
    Args:
        documents: Список документов
        llm: LLM (опционально)
        
    Returns:
        (обзор, список_источников)
    """
    service = MapReduceService(llm=llm)
    result = await service.process(documents, "Сделай обзор документов", task_type="summarize")
    return result.answer, result.sources


async def map_reduce_extract(
    documents: List[Document],
    llm=None
) -> Tuple[str, List[str]]:
    """
    Извлечение сущностей из документов с использованием Map-Reduce.
    
    Args:
        documents: Список документов
        llm: LLM (опционально)
        
    Returns:
        (извлечённые_факты, список_источников)
    """
    service = MapReduceService(llm=llm)
    result = await service.process(documents, "Извлеки ключевые факты", task_type="extract")
    return result.answer, result.sources


