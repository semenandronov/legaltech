"""Smart Column Service for creating columns from natural language descriptions and examples"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.tabular_review import TabularReview, TabularColumn
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


class ColumnDescription(BaseModel):
    """Structured output for column creation from description"""
    column_label: str = Field(description="Name/label of the column")
    column_type: str = Field(description="Type: text, bulleted_list, number, currency, yes_no, date, tag, multiple_tags, verbatim")
    prompt: str = Field(description="Extraction prompt for AI")
    column_config: Optional[Dict[str, Any]] = Field(None, description="Configuration for tag/multiple_tags: {options: [{label, color}], allow_custom: bool}")
    validation_rules: Optional[Dict[str, Any]] = Field(None, description="Additional validation rules if needed")


class Example(BaseModel):
    """Example for column creation from examples"""
    document_text: str = Field(description="Text from document")
    expected_value: str = Field(description="Expected extracted value")
    context: Optional[str] = Field(None, description="Additional context")


class SmartColumnService:
    """Service for smart column creation from descriptions and examples"""
    
    def __init__(self, db: Session):
        """Initialize smart column service"""
        self.db = db
        try:
            self.llm = create_llm(temperature=0.3)  # Slightly higher for more creative responses
        except Exception as e:
            self.llm = None
            logger.warning(f"GigaChat not configured: {e}, smart column creation will not work")
    
    async def create_column_from_description(
        self,
        review_id: str,
        description: str
    ) -> TabularColumn:
        """
        Create a column from natural language description
        
        Args:
            review_id: Tabular review ID
            description: Natural language description (e.g., "Найди пункт о неустойке и выпиши размер и условие начисления")
        
        Returns:
            Created TabularColumn
        """
        if not self.llm:
            raise ValueError("LLM not configured")
        
        # Verify review exists
        review = self.db.query(TabularReview).filter(TabularReview.id == review_id).first()
        if not review:
            raise ValueError(f"Tabular review {review_id} not found")
        
        # Build prompt for column generation
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты эксперт по созданию колонок для извлечения информации из юридических документов.

Твоя задача: проанализировать описание на естественном языке и создать определение колонки.

Типы колонок:
- text: свободный текст
- bulleted_list: маркированный список
- number: числовое значение
- currency: денежная сумма с валютой
- yes_no: да/нет (boolean)
- date: дата
- tag: один тег из предопределенного списка
- multiple_tags: несколько тегов из предопределенного списка
- verbatim: точная цитата из документа

Определи:
1. column_label: короткое название колонки
2. column_type: наиболее подходящий тип
3. prompt: четкий промпт для AI-извлечения (на английском)
4. column_config: если tag/multiple_tags - предложи опции
5. validation_rules: дополнительные правила валидации (если нужны)

ВАЖНО:
- Промпт должен быть четким и конкретным
- Для tag/multiple_tags обязательно предложи список опций
- Учитывай контекст юридических документов"""),
            ("human", f"""Создай колонку на основе описания:

"{description}"

Верни структурированное определение колонки.""")
        ])
        
        try:
            # Use structured output
            structured_llm = self.llm.with_structured_output(
                ColumnDescription,
                method="json_schema"
            )
            chain = prompt | structured_llm
            result = await chain.ainvoke({})
            
            # Get max order_index
            max_order = self.db.query(TabularColumn.order_index).filter(
                TabularColumn.tabular_review_id == review_id
            ).order_by(TabularColumn.order_index.desc()).first()
            order_index = (max_order[0] + 1) if max_order else 0
            
            # Create column
            column = TabularColumn(
                tabular_review_id=review_id,
                column_label=result.column_label,
                column_type=result.column_type,
                prompt=result.prompt,
                column_config=result.column_config,
                order_index=order_index
            )
            
            self.db.add(column)
            self.db.commit()
            self.db.refresh(column)
            
            logger.info(f"Created smart column from description: {column.id} ({column.column_label})")
            return column
            
        except Exception as e:
            logger.error(f"Error creating column from description: {e}", exc_info=True)
            raise ValueError(f"Failed to create column from description: {str(e)}")
    
    async def create_column_from_examples(
        self,
        review_id: str,
        examples: List[Example]
    ) -> TabularColumn:
        """
        Create a column from examples (few-shot learning)
        
        Args:
            review_id: Tabular review ID
            examples: List of examples with document text and expected values
        
        Returns:
            Created TabularColumn
        """
        if not self.llm:
            raise ValueError("LLM not configured")
        
        if len(examples) < 2:
            raise ValueError("At least 2 examples are required")
        
        # Verify review exists
        review = self.db.query(TabularReview).filter(TabularReview.id == review_id).first()
        if not review:
            raise ValueError(f"Tabular review {review_id} not found")
        
        # Format examples for prompt
        examples_text = "\n\n".join([
            f"Пример {i+1}:\nДокумент: {ex.document_text[:500]}...\nОжидаемое значение: {ex.expected_value}"
            for i, ex in enumerate(examples)
        ])
        
        # Build prompt for pattern analysis
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты эксперт по анализу паттернов в документах.

Твоя задача: проанализировать примеры и определить:
1. Какой паттерн используется для извлечения значения
2. Какой тип колонки подходит
3. Какой промпт будет работать для всех примеров

Типы колонок:
- text: свободный текст
- bulleted_list: маркированный список
- number: числовое значение
- currency: денежная сумма с валютой
- yes_no: да/нет
- date: дата
- tag: один тег из предопределенного списка
- multiple_tags: несколько тегов
- verbatim: точная цитата

Проанализируй паттерны и создай определение колонки, которое будет работать для всех примеров."""),
            ("human", f"""Проанализируй следующие примеры и создай определение колонки:

{examples_text}

Определи паттерн и создай колонку, которая будет извлекать значения по этому паттерну.""")
        ])
        
        try:
            # Use structured output
            structured_llm = self.llm.with_structured_output(
                ColumnDescription,
                method="json_schema"
            )
            chain = prompt | structured_llm
            result = await chain.ainvoke({})
            
            # Store examples in column_config for few-shot learning
            if not result.column_config:
                result.column_config = {}
            result.column_config["examples"] = [
                {
                    "document_text": ex.document_text,
                    "expected_value": ex.expected_value,
                    "context": ex.context
                }
                for ex in examples
            ]
            
            # Get max order_index
            max_order = self.db.query(TabularColumn.order_index).filter(
                TabularColumn.tabular_review_id == review_id
            ).order_by(TabularColumn.order_index.desc()).first()
            order_index = (max_order[0] + 1) if max_order else 0
            
            # Create column
            column = TabularColumn(
                tabular_review_id=review_id,
                column_label=result.column_label,
                column_type=result.column_type,
                prompt=result.prompt,
                column_config=result.column_config,
                order_index=order_index
            )
            
            self.db.add(column)
            self.db.commit()
            self.db.refresh(column)
            
            logger.info(f"Created smart column from examples: {column.id} ({column.column_label})")
            return column
            
        except Exception as e:
            logger.error(f"Error creating column from examples: {e}", exc_info=True)
            raise ValueError(f"Failed to create column from examples: {str(e)}")

