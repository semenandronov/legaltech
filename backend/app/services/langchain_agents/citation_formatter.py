"""Форматтер юридических цитат по ГОСТ Р 7.0.5-2008"""
from typing import Optional, Dict, Any, List
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class LegalCitationFormatter:
    """
    Форматтер юридических цитат по ГОСТ Р 7.0.5-2008.
    
    Поддерживает:
    - Форматирование ссылок на законодательство ("п. 1 ст. 393 ГК РФ")
    - Форматирование ссылок на судебные решения (ГОСТ Р 7.0.5-2008)
    - Форматирование ссылок на постановления ВС РФ
    """
    
    # Маппинг сокращений кодексов
    CODE_NAMES = {
        "ГК": "Гражданский кодекс Российской Федерации",
        "ГПК": "Гражданский процессуальный кодекс Российской Федерации",
        "АПК": "Арбитражный процессуальный кодекс Российской Федерации",
        "УК": "Уголовный кодекс Российской Федерации",
        "ТК": "Трудовой кодекс Российской Федерации",
        "НК": "Налоговый кодекс Российской Федерации",
        "ГК РФ": "Гражданский кодекс Российской Федерации",
        "ГПК РФ": "Гражданский процессуальный кодекс Российской Федерации",
        "АПК РФ": "Арбитражный процессуальный кодекс Российской Федерации",
        "УК РФ": "Уголовный кодекс Российской Федерации",
        "ТК РФ": "Трудовой кодекс Российской Федерации",
        "НК РФ": "Налоговый кодекс Российской Федерации",
    }
    
    def format_legislation_citation(
        self,
        code: str,
        article: str,
        part: Optional[str] = None,
        paragraph: Optional[str] = None,
        subparagraph: Optional[str] = None,
        full: bool = False
    ) -> str:
        """
        Форматирует ссылку на статью кодекса
        
        Args:
            code: Название кодекса (ГК, АПК, и т.д.)
            article: Номер статьи
            part: Номер части (опционально)
            paragraph: Номер пункта (опционально)
            subparagraph: Номер подпункта (опционально)
            full: Использовать полное название кодекса (опционально)
        
        Returns:
            Отформатированная ссылка (например: "п. 1 ст. 393 ГК РФ")
        """
        code_name = self.CODE_NAMES.get(code, code) if full else code
        
        # Формируем ссылку снизу вверх (от подпункта к статье)
        parts = []
        
        if subparagraph:
            parts.append(f"подп. {subparagraph}")
        
        if paragraph:
            parts.append(f"п. {paragraph}")
        
        if part:
            parts.append(f"ч. {part}")
        
        if parts:
            citation = f"{', '.join(parts)} ст. {article} {code_name}"
        else:
            citation = f"ст. {article} {code_name}"
        
        return citation
    
    def format_court_decision(
        self,
        court_name: str,
        case_number: Optional[str] = None,
        decision_date: Optional[datetime] = None,
        full_format: bool = False
    ) -> str:
        """
        Форматирует ссылку на судебное решение по ГОСТ Р 7.0.5-2008
        
        Args:
            court_name: Название суда
            case_number: Номер дела (опционально)
            decision_date: Дата решения (опционально)
            full_format: Полный формат с датой
        
        Returns:
            Отформатированная ссылка (например: "Решение Арбитражного суда г. Москвы от 01.01.2023 по делу № А40-12345/2023")
        """
        citation_parts = [f"Решение {court_name}"]
        
        if decision_date:
            date_str = decision_date.strftime("%d.%m.%Y")
            citation_parts.append(f"от {date_str}")
        
        if case_number:
            citation_parts.append(f"по делу № {case_number}")
        
        return " ".join(citation_parts)
    
    def format_supreme_court_resolution(
        self,
        resolution_type: str,
        number: Optional[str] = None,
        date: Optional[datetime] = None,
        title: Optional[str] = None
    ) -> str:
        """
        Форматирует ссылку на постановление Пленума ВС РФ
        
        Args:
            resolution_type: Тип постановления (например: "Пленума Верховного Суда РФ")
            number: Номер постановления (опционально)
            date: Дата постановления (опционально)
            title: Название постановления (опционально)
        
        Returns:
            Отформатированная ссылка (например: "Постановление Пленума Верховного Суда РФ от 24.03.2016 № 7")
        """
        citation_parts = [f"Постановление {resolution_type}"]
        
        if date:
            date_str = date.strftime("%d.%m.%Y")
            citation_parts.append(f"от {date_str}")
        
        if number:
            citation_parts.append(f"№ {number}")
        
        if title:
            citation_parts.append(f'"{title}"')
        
        return " ".join(citation_parts)
    
    def format_case_citation(
        self,
        case_number: str,
        court: Optional[str] = None,
        date: Optional[datetime] = None
    ) -> str:
        """
        Форматирует ссылку на дело из картотеки
        
        Args:
            case_number: Номер дела (например: "А40-12345/2023")
            court: Название суда (опционально)
            date: Дата дела (опционально)
        
        Returns:
            Отформатированная ссылка
        """
        citation_parts = []
        
        if court:
            citation_parts.append(court)
        
        if date:
            date_str = date.strftime("%d.%m.%Y")
            citation_parts.append(f"от {date_str}")
        
        citation_parts.append(f"№ {case_number}")
        
        return " ".join(citation_parts) if citation_parts else f"№ {case_number}"
    
    def parse_citation(self, citation_text: str) -> Optional[Dict[str, Any]]:
        """
        Парсит цитату из текста для нормализации
        
        Args:
            citation_text: Текст цитаты (например: "ст. 393 ГК РФ")
        
        Returns:
            Словарь с распарсенными полями или None
        """
        # Паттерны для распознавания цитат
        patterns = [
            # "ст. 393 ГК РФ"
            r"ст\.?\s+(\d+)\s+([А-Я]+(?:\s+РФ)?)",
            # "п. 1 ст. 393 ГК РФ"
            r"п\.?\s+(\d+)\s+ст\.?\s+(\d+)\s+([А-Я]+(?:\s+РФ)?)",
            # "ч. 2 ст. 393 ГК РФ"
            r"ч\.?\s+(\d+)\s+ст\.?\s+(\d+)\s+([А-Я]+(?:\s+РФ)?)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, citation_text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    # Простой формат: статья кодекс
                    return {
                        "type": "legislation",
                        "article": groups[0],
                        "code": groups[1].replace(" РФ", "").strip()
                    }
                elif len(groups) == 3:
                    # Формат с частью/пунктом
                    return {
                        "type": "legislation",
                        "article": groups[1],
                        "code": groups[2].replace(" РФ", "").strip(),
                        "part": groups[0] if "ч" in pattern else None,
                        "paragraph": groups[0] if "п" in pattern else None
                    }
        
        return None
    
    def normalize_citation(self, citation_text: str) -> str:
        """
        Нормализует цитату к стандартному формату
        
        Args:
            citation_text: Текст цитаты
        
        Returns:
            Нормализованная цитата
        """
        parsed = self.parse_citation(citation_text)
        if parsed and parsed["type"] == "legislation":
            return self.format_legislation_citation(
                code=parsed["code"],
                article=parsed["article"],
                part=parsed.get("part"),
                paragraph=parsed.get("paragraph")
            )
        
        return citation_text

