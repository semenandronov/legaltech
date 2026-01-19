"""Clause Extractor Service - извлечение пунктов из контрактов"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from app.services.llm_factory import create_llm
import logging
import re
import json

logger = logging.getLogger(__name__)


class ExtractedClause(BaseModel):
    """Extracted clause from a contract"""
    category: str = Field(description="Категория пункта (confidentiality, termination, liability, etc.)")
    title: str = Field(description="Заголовок или номер пункта")
    text: str = Field(description="Полный текст пункта")
    location: Dict[str, Any] = Field(default_factory=dict, description="Расположение в документе (page, section)")
    summary: str = Field(default="", description="Краткое резюме пункта")
    key_values: Dict[str, Any] = Field(default_factory=dict, description="Ключевые значения (сроки, суммы)")


class ClauseExtractionResult(BaseModel):
    """Result of clause extraction"""
    clauses: List[ExtractedClause] = Field(default_factory=list, description="Извлечённые пункты")
    document_type: str = Field(default="unknown", description="Тип документа")
    parties: List[str] = Field(default_factory=list, description="Стороны договора")
    date: Optional[str] = Field(default=None, description="Дата договора")
    contract_number: Optional[str] = Field(default=None, description="Номер договора")


# Промпт для извлечения пунктов
CLAUSE_EXTRACTION_PROMPT = """Ты - эксперт по анализу юридических документов. Твоя задача - извлечь все значимые пункты из контракта.

ТЕКСТ ДОКУМЕНТА:
{document_text}

ЗАДАЧА:
1. Определи тип документа (NDA, договор услуг, поставки и т.д.)
2. Извлеки стороны договора
3. Найди дату и номер договора
4. Извлеки ВСЕ значимые пункты договора по категориям

КАТЕГОРИИ ПУНКТОВ:
- confidentiality: Конфиденциальность
- termination: Расторжение договора
- liability: Ответственность
- indemnification: Возмещение убытков
- intellectual_property: Интеллектуальная собственность
- data_protection: Защита данных
- payment: Оплата
- warranties: Гарантии
- force_majeure: Форс-мажор
- dispute_resolution: Разрешение споров
- governing_law: Применимое право
- assignment: Уступка прав
- non_compete: Неконкуренция
- non_solicitation: Непереманивание
- audit_rights: Право на аудит
- insurance: Страхование
- compliance: Соответствие требованиям
- change_of_control: Смена контроля
- notice: Уведомления
- amendments: Изменения и дополнения
- other: Другое

Для каждого пункта укажи:
- category: категория из списка выше
- title: заголовок или номер пункта (например "Статья 5. Конфиденциальность" или "п. 3.2")
- text: полный текст пункта
- location: {{"section": "номер раздела", "paragraph": "номер параграфа"}}
- summary: краткое резюме (1-2 предложения)
- key_values: ключевые значения (сроки, суммы, проценты)

Примеры key_values:
- Для срока: {{"duration": "3 года", "duration_type": "confidentiality"}}
- Для суммы: {{"amount": 1000000, "currency": "RUB", "purpose": "penalty"}}
- Для уведомления: {{"notice_period": "30 дней", "notice_type": "termination"}}

ВАЖНО:
- Извлекай ПОЛНЫЙ текст пункта, не сокращай
- Если пункт относится к нескольким категориям, выбери основную
- Для key_values извлекай конкретные числа и сроки
- Если в документе нет какой-то категории, не добавляй её

Верни результат в формате JSON:
{{
    "document_type": "тип документа",
    "parties": ["Сторона 1", "Сторона 2"],
    "date": "дата договора или null",
    "contract_number": "номер договора или null",
    "clauses": [
        {{
            "category": "категория",
            "title": "заголовок",
            "text": "полный текст",
            "location": {{"section": "...", "paragraph": "..."}},
            "summary": "краткое резюме",
            "key_values": {{}}
        }}
    ]
}}"""

# Промпт для извлечения конкретной категории
CATEGORY_EXTRACTION_PROMPT = """Ты - эксперт по анализу юридических документов.

ТЕКСТ ДОКУМЕНТА:
{document_text}

ЗАДАЧА:
Найди и извлеки пункт договора, относящийся к категории: {category}
Категория: {category_description}

Если пункт найден, верни JSON:
{{
    "found": true,
    "title": "заголовок или номер пункта",
    "text": "полный текст пункта",
    "location": {{"section": "номер раздела"}},
    "summary": "краткое резюме",
    "key_values": {{
        // ключевые значения из пункта
    }}
}}

Если пункт НЕ найден, верни:
{{
    "found": false,
    "reason": "причина почему не найден"
}}

ВАЖНО: Извлекай ПОЛНЫЙ текст пункта, не сокращай."""


class ClauseExtractor:
    """
    Сервис для извлечения пунктов из контрактов с помощью LLM.
    
    Поддерживает:
    - Полное извлечение всех пунктов
    - Извлечение конкретной категории
    - Кэширование результатов
    """
    
    def __init__(self):
        """Initialize clause extractor"""
        self.llm = None
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM"""
        try:
            # Use use_rate_limiting=False for LangChain | operator compatibility
            self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
            logger.info("ClauseExtractor: LLM initialized")
        except Exception as e:
            logger.warning(f"ClauseExtractor: Failed to initialize LLM: {e}")
            self.llm = None
    
    async def extract_all_clauses(
        self,
        document_text: str,
        max_length: int = 50000
    ) -> ClauseExtractionResult:
        """
        Extract all clauses from a document
        
        Args:
            document_text: Full document text
            max_length: Maximum text length to process
            
        Returns:
            ClauseExtractionResult with all extracted clauses
        """
        if not self.llm:
            logger.error("LLM not initialized")
            return ClauseExtractionResult()
        
        # Truncate if too long
        if len(document_text) > max_length:
            logger.warning(f"Document too long ({len(document_text)}), truncating to {max_length}")
            document_text = document_text[:max_length]
        
        try:
            # Create prompt
            prompt = ChatPromptTemplate.from_template(CLAUSE_EXTRACTION_PROMPT)
            
            # Create chain
            chain = prompt | self.llm
            
            # Execute
            response = await chain.ainvoke({"document_text": document_text})
            
            # Parse response
            result = self._parse_extraction_response(response.content)
            
            logger.info(f"Extracted {len(result.clauses)} clauses from document")
            return result
            
        except Exception as e:
            logger.error(f"Error extracting clauses: {e}", exc_info=True)
            return ClauseExtractionResult()
    
    async def extract_clause_by_category(
        self,
        document_text: str,
        category: str,
        category_description: str = ""
    ) -> Optional[ExtractedClause]:
        """
        Extract a specific clause category from document
        
        Args:
            document_text: Full document text
            category: Category to extract
            category_description: Description of the category
            
        Returns:
            Extracted clause or None
        """
        if not self.llm:
            logger.error("LLM not initialized")
            return None
        
        # Default descriptions
        category_descriptions = {
            "confidentiality": "Пункты о конфиденциальности, неразглашении информации, NDA условия",
            "termination": "Условия расторжения договора, порядок прекращения отношений",
            "liability": "Ограничение ответственности, штрафные санкции, пени",
            "indemnification": "Возмещение убытков, компенсации",
            "intellectual_property": "Права на интеллектуальную собственность, лицензии, авторские права",
            "data_protection": "Защита персональных данных, GDPR, обработка данных",
            "payment": "Условия оплаты, порядок расчетов, цена",
            "warranties": "Гарантии, заверения сторон",
            "force_majeure": "Форс-мажор, обстоятельства непреодолимой силы",
            "dispute_resolution": "Разрешение споров, арбитраж, медиация",
            "governing_law": "Применимое право, юрисдикция",
            "change_of_control": "Условия при смене контроля, смене владельца",
            "notice": "Порядок уведомлений, адреса для корреспонденции",
        }
        
        if not category_description:
            category_description = category_descriptions.get(category, f"Пункты категории {category}")
        
        try:
            # Truncate document
            max_length = 40000
            if len(document_text) > max_length:
                document_text = document_text[:max_length]
            
            # Create prompt
            prompt = ChatPromptTemplate.from_template(CATEGORY_EXTRACTION_PROMPT)
            
            # Create chain
            chain = prompt | self.llm
            
            # Execute
            response = await chain.ainvoke({
                "document_text": document_text,
                "category": category,
                "category_description": category_description
            })
            
            # Parse response
            result = self._parse_category_response(response.content, category)
            
            if result:
                logger.info(f"Extracted clause for category '{category}'")
            else:
                logger.info(f"No clause found for category '{category}'")
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting category {category}: {e}", exc_info=True)
            return None
    
    def extract_clauses_with_regex(
        self,
        document_text: str
    ) -> List[Dict[str, Any]]:
        """
        Extract clauses using regex patterns (fast, no LLM)
        
        Args:
            document_text: Full document text
            
        Returns:
            List of clause dictionaries
        """
        clauses = []
        
        # Patterns for common clause structures
        patterns = [
            # Numbered sections: "1. Title" or "1.1. Title" or "1.1.1 Title"
            r'(?P<section>\d+(?:\.\d+)*\.?)\s*(?P<title>[А-ЯЁA-Z][^\n]{5,100})\n(?P<text>(?:(?!\n\d+(?:\.\d+)*\.?\s+[А-ЯЁA-Z]).)*)',
            # Article format: "Статья 1. Title"
            r'(?:Статья|Раздел|Глава)\s+(?P<section>\d+)\.?\s*(?P<title>[^\n]+)\n(?P<text>(?:(?!(?:Статья|Раздел|Глава)\s+\d+).)*)',
            # Roman numerals: "I. Title"
            r'(?P<section>[IVXLCDM]+)\.\s*(?P<title>[^\n]+)\n(?P<text>(?:(?![IVXLCDM]+\.\s+).)*)',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, document_text, re.DOTALL | re.MULTILINE):
                groups = match.groupdict()
                clause = {
                    "title": f"{groups.get('section', '')} {groups.get('title', '')}".strip(),
                    "text": groups.get('text', '').strip()[:2000],  # Limit text length
                    "location": {"section": groups.get('section', '')},
                    "category": "other",  # Will be categorized later
                }
                if len(clause["text"]) > 50:  # Filter very short matches
                    clauses.append(clause)
        
        logger.info(f"Regex extraction found {len(clauses)} potential clauses")
        return clauses
    
    def _parse_extraction_response(self, response: str) -> ClauseExtractionResult:
        """Parse LLM response for full extraction"""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                logger.warning("No JSON found in response")
                return ClauseExtractionResult()
            
            data = json.loads(json_match.group())
            
            # Parse clauses
            clauses = []
            for clause_data in data.get("clauses", []):
                try:
                    clause = ExtractedClause(
                        category=clause_data.get("category", "other"),
                        title=clause_data.get("title", ""),
                        text=clause_data.get("text", ""),
                        location=clause_data.get("location", {}),
                        summary=clause_data.get("summary", ""),
                        key_values=clause_data.get("key_values", {})
                    )
                    clauses.append(clause)
                except Exception as e:
                    logger.warning(f"Failed to parse clause: {e}")
            
            return ClauseExtractionResult(
                clauses=clauses,
                document_type=data.get("document_type", "unknown"),
                parties=data.get("parties", []),
                date=data.get("date"),
                contract_number=data.get("contract_number")
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return ClauseExtractionResult()
    
    def _parse_category_response(
        self,
        response: str,
        category: str
    ) -> Optional[ExtractedClause]:
        """Parse LLM response for category extraction"""
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                logger.warning("No JSON found in category response")
                return None
            
            data = json.loads(json_match.group())
            
            if not data.get("found", False):
                return None
            
            return ExtractedClause(
                category=category,
                title=data.get("title", ""),
                text=data.get("text", ""),
                location=data.get("location", {}),
                summary=data.get("summary", ""),
                key_values=data.get("key_values", {})
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse category JSON response: {e}")
            return None
    
    def categorize_clause(
        self,
        clause_text: str,
        clause_title: str = ""
    ) -> str:
        """
        Categorize a clause based on its text (rule-based, no LLM)
        
        Args:
            clause_text: Clause text
            clause_title: Clause title
            
        Returns:
            Category name
        """
        text = (clause_title + " " + clause_text).lower()
        
        # Category keywords
        category_keywords = {
            "confidentiality": ["конфиденциальн", "неразглашен", "секрет", "nda", "тайн"],
            "termination": ["расторжен", "прекращен", "terminat", "отказ от договора"],
            "liability": ["ответственност", "штраф", "пен", "санкц", "liability"],
            "indemnification": ["возмещен", "убыт", "компенсац", "indemn"],
            "intellectual_property": ["интеллектуальн", "авторск", "патент", "лицензи", "ip"],
            "data_protection": ["персональн", "данн", "gdpr", "обработк", "privacy"],
            "payment": ["оплат", "платеж", "цен", "стоимост", "вознагражден"],
            "warranties": ["гарант", "заверен", "warrant"],
            "force_majeure": ["форс-мажор", "непреодолим", "force majeure"],
            "dispute_resolution": ["спор", "арбитраж", "суд", "медиац"],
            "governing_law": ["применим", "право", "юрисдикц", "governing law"],
            "change_of_control": ["смен", "контрол", "change of control"],
            "notice": ["уведомлен", "извещен", "notice"],
            "insurance": ["страхов"],
            "non_compete": ["конкуренц", "non-compete"],
            "audit_rights": ["аудит", "провер"],
        }
        
        for category, keywords in category_keywords.items():
            for keyword in keywords:
                if keyword in text:
                    return category
        
        return "other"

