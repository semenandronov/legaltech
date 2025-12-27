"""Tabular Chat service for analyzing table data"""
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.services.tabular_review_service import TabularReviewService
from app.services.llm_factory import create_llm
from app.config import config
import logging
import json

logger = logging.getLogger(__name__)


class TabularChatService:
    """Service for chat over table functionality"""
    
    def __init__(self, db: Session):
        """Initialize tabular chat service"""
        self.db = db
        self.tabular_service = TabularReviewService(db)
        
        # Initialize LLM
        try:
            self.llm = create_llm(temperature=0.3)  # Slightly higher for more natural responses
        except Exception as e:
            self.llm = None
            logger.warning(f"GigaChat not configured: {e}, tabular chat will not work")
    
    def format_table_data_for_llm(self, table_data: Dict[str, Any]) -> str:
        """Format table data as text for LLM context"""
        columns = table_data.get("columns", [])
        rows = table_data.get("rows", [])
        
        # Build column headers
        column_headers = ["Document"] + [col["column_label"] for col in columns]
        
        # Build rows
        formatted_rows = []
        for row in rows:
            row_data = [row["file_name"]]
            for col in columns:
                cell = row["cells"].get(col["id"], {})
                cell_value = cell.get("cell_value") or "-"
                row_data.append(str(cell_value))
            formatted_rows.append(" | ".join(row_data))
        
        # Format as markdown table
        table_text = " | ".join(column_headers) + "\n"
        table_text += " | ".join(["---"] * len(column_headers)) + "\n"
        table_text += "\n".join(formatted_rows)
        
        return table_text
    
    async def analyze_table(
        self,
        review_id: str,
        question: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Analyze table data and answer question"""
        if not self.llm:
            raise ValueError("LLM not configured")
        
        # Get table data
        table_data = self.tabular_service.get_table_data(review_id, user_id)
        
        # Format table for LLM
        table_text = self.format_table_data_for_llm(table_data)
        
        # Build prompt
        system_prompt = """Ты — опытный юрист-аналитик, специализирующийся на анализе табличных данных из юридических документов.

Твоя задача — отвечать на вопросы пользователя на основе данных в таблице.

ВАЖНО:
1. Отвечай на русском языке
2. Используй конкретные данные из таблицы (названия документов, значения ячеек)
3. Указывай источники (названия документов, номера строк)
4. Если данных недостаточно, честно скажи об этом
5. Выявляй закономерности, противоречия, риски
6. Форматируй ответ с использованием markdown (жирный текст, списки, таблицы)"""

        user_prompt = f"""Вот таблица с данными из юридических документов:

{table_text}

Вопрос пользователя: {question}

Ответь на вопрос, используя данные из таблицы. Указывай конкретные документы и значения."""

        # Call LLM
        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = await self.llm.ainvoke(messages)
        answer = response.content.strip() if hasattr(response, 'content') else str(response).strip()
        
        # Extract citations (find document names mentioned in answer)
        citations = []
        for row in table_data.get("rows", []):
            if row["file_name"].lower() in answer.lower():
                citations.append({
                    "file": row["file_name"],
                    "file_id": row["file_id"],
                })
        
        return {
            "answer": answer,
            "citations": citations,
            "table_stats": {
                "total_rows": len(table_data.get("rows", [])),
                "total_columns": len(table_data.get("columns", [])),
            }
        }

