"""LexNLP Extractor - wrapper for LexNLP library for legal text extraction"""
from typing import List, Dict, Any, Optional
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import LexNLP
# LexNLP временно отключен из-за несовместимости gensim 4.1.2 с Python 3.13
# Код работает с regex fallbacks
LEXNLP_AVAILABLE = False
try:
    # Попытка импорта отключена до решения проблемы с зависимостями
    # from lexnlp.extract.en.dates import get_dates
    # from lexnlp.extract.en.amounts import get_amounts
    # from lexnlp.extract.en.money import get_money
    # LEXNLP_AVAILABLE = True
    # logger.info("✅ LexNLP imported successfully")
    pass
except ImportError as e:
    logger.warning(f"LexNLP not available: {e}. Some extraction features will be limited.")
    LEXNLP_AVAILABLE = False


class LexNLPExtractor:
    """
    Wrapper для LexNLP библиотеки для извлечения юридически значимых данных.
    
    Интегрирует LexNLP с поддержкой русского языка через дополнительные regex patterns.
    """
    
    def __init__(self):
        """Initialize LexNLP extractor"""
        self.available = LEXNLP_AVAILABLE
        
        # Russian date patterns (дополнительно к LexNLP)
        self.russian_date_patterns = [
            r'\d{1,2}\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4}',
            r'\d{1,2}\.\d{1,2}\.\d{4}',  # DD.MM.YYYY
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
        ]
        
        # Russian amount patterns
        self.russian_amount_patterns = [
            r'\d{1,3}(?:\s?\d{3})*(?:\s?руб[\.лей]*)?',
            r'\d+\.\d+\s*руб[\.лей]*',
            r'\d{1,3}(?:\s?\d{3})*(?:\s?USD|EUR|USD|EUR)?',
        ]
        
        # Month names mapping
        self.month_names = {
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
            'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
            'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
        }
    
    def extract_dates(self, text: str) -> List[Dict[str, Any]]:
        """
        Извлекает даты из текста
        
        Args:
            text: Текст для анализа
            
        Returns:
            List of dictionaries with date information:
            [
                {
                    "date": "2024-01-15",
                    "original_text": "15 января 2024",
                    "confidence": 0.95,
                    "source": "lexnlp" or "regex"
                }
            ]
        """
        dates = []
        
        if not text:
            return dates
        
        # Используем LexNLP если доступен (для английских дат)
        if self.available:
            try:
                lexnlp_dates = list(get_dates(text))
                for date_obj in lexnlp_dates:
                    if isinstance(date_obj, datetime):
                        dates.append({
                            "date": date_obj.strftime("%Y-%m-%d"),
                            "original_text": str(date_obj),
                            "confidence": 0.9,
                            "source": "lexnlp"
                        })
                    elif isinstance(date_obj, dict):
                        # LexNLP может вернуть словарь
                        if 'date' in date_obj:
                            dates.append({
                                "date": date_obj['date'].strftime("%Y-%m-%d") if isinstance(date_obj['date'], datetime) else str(date_obj['date']),
                                "original_text": date_obj.get('text', str(date_obj)),
                                "confidence": 0.9,
                                "source": "lexnlp"
                            })
            except Exception as e:
                logger.debug(f"LexNLP date extraction error: {e}")
        
        # Дополнительно извлекаем русские даты через regex
        for pattern in self.russian_date_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                date_str = match.group(0)
                try:
                    parsed_date = self._parse_russian_date(date_str)
                    if parsed_date:
                        # Проверяем, не добавлена ли уже эта дата
                        if not any(d.get("original_text") == date_str for d in dates):
                            dates.append({
                                "date": parsed_date,
                                "original_text": date_str,
                                "confidence": 0.85,
                                "source": "regex"
                            })
                except Exception as e:
                    logger.debug(f"Error parsing Russian date '{date_str}': {e}")
        
        return dates
    
    def _parse_russian_date(self, date_str: str) -> Optional[str]:
        """Парсит русскую дату в формат YYYY-MM-DD"""
        try:
            # Формат: "15 января 2024"
            for month_name, month_num in self.month_names.items():
                if month_name in date_str.lower():
                    parts = date_str.split()
                    day = int(parts[0])
                    year = int(parts[-1])
                    return f"{year}-{month_num:02d}-{day:02d}"
            
            # Формат: "15.01.2024" (DD.MM.YYYY)
            if '.' in date_str:
                parts = date_str.split('.')
                if len(parts) == 3:
                    day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                    return f"{year}-{month:02d}-{day:02d}"
            
            # Формат: "2024-01-15" (уже правильный)
            if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                return date_str
            
        except Exception as e:
            logger.debug(f"Error parsing date '{date_str}': {e}")
        
        return None
    
    def extract_amounts(self, text: str) -> List[Dict[str, Any]]:
        """
        Извлекает денежные суммы из текста
        
        Args:
            text: Текст для анализа
            
        Returns:
            List of dictionaries with amount information:
            [
                {
                    "amount": 1500000,
                    "currency": "RUB",
                    "original_text": "1 500 000 рублей",
                    "confidence": 0.9,
                    "source": "lexnlp" or "regex"
                }
            ]
        """
        amounts = []
        
        if not text:
            return amounts
        
        # Используем LexNLP если доступен
        if self.available:
            try:
                lexnlp_amounts = list(get_amounts(text))
                for amount_obj in lexnlp_amounts:
                    if isinstance(amount_obj, (int, float)):
                        amounts.append({
                            "amount": float(amount_obj),
                            "currency": "USD",  # LexNLP defaults to USD
                            "original_text": str(amount_obj),
                            "confidence": 0.9,
                            "source": "lexnlp"
                        })
                    elif isinstance(amount_obj, dict):
                        amounts.append({
                            "amount": float(amount_obj.get('amount', 0)),
                            "currency": amount_obj.get('currency', 'USD'),
                            "original_text": amount_obj.get('text', str(amount_obj)),
                            "confidence": 0.9,
                            "source": "lexnlp"
                        })
            except Exception as e:
                logger.debug(f"LexNLP amount extraction error: {e}")
        
        # Дополнительно извлекаем русские суммы через regex
        for pattern in self.russian_amount_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                amount_str = match.group(0)
                try:
                    # Извлекаем число (убираем пробелы и валюту)
                    number_str = re.sub(r'[^\d.,]', '', amount_str)
                    number_str = number_str.replace(' ', '').replace(',', '.')
                    
                    # Определяем валюту
                    currency = "RUB"
                    if 'USD' in amount_str.upper() or '$' in amount_str:
                        currency = "USD"
                    elif 'EUR' in amount_str.upper() or '€' in amount_str:
                        currency = "EUR"
                    elif 'руб' in amount_str.lower():
                        currency = "RUB"
                    
                    amount_value = float(number_str)
                    
                    # Проверяем, не добавлена ли уже эта сумма
                    if not any(
                        abs(a.get("amount", 0) - amount_value) < 0.01 and 
                        a.get("currency") == currency 
                        for a in amounts
                    ):
                        amounts.append({
                            "amount": amount_value,
                            "currency": currency,
                            "original_text": amount_str,
                            "confidence": 0.85,
                            "source": "regex"
                        })
                except Exception as e:
                    logger.debug(f"Error parsing amount '{amount_str}': {e}")
        
        return amounts
    
    def extract_money(self, text: str) -> List[Dict[str, Any]]:
        """
        Извлекает валютные суммы из текста (более детально чем extract_amounts)
        
        Args:
            text: Текст для анализа
            
        Returns:
            List of dictionaries with money information (similar to extract_amounts)
        """
        # Используем extract_amounts как базу, но можем добавить специфичную логику
        return self.extract_amounts(text)
    
    def extract_entities(self, text: str, entity_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Извлекает именованные сущности из текста
        
        Args:
            text: Текст для анализа
            entity_types: Типы сущностей для извлечения (если None, извлекает все)
            
        Returns:
            List of dictionaries with entity information:
            [
                {
                    "text": "ООО Ромашка",
                    "type": "ORG",
                    "confidence": 0.8,
                    "source": "regex"
                }
            ]
        """
        entities = []
        
        if not text:
            return entities
        
        # Простые паттерны для русского языка (можно расширить)
        # Организации (ООО, ЗАО, АО и т.д.)
        org_patterns = [
            r'(?:ООО|ЗАО|АО|ПАО|ИП|ОАО)\s+[""]?([А-ЯЁ][А-Яа-яё\s-]+)[""]?',
            r'([А-ЯЁ][А-Яа-яё\s-]+)\s+(?:ООО|ЗАО|АО|ПАО)',
        ]
        
        # Имена (ФИО)
        name_patterns = [
            r'([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+)',  # Ф И О
        ]
        
        if entity_types is None or "ORG" in entity_types:
            for pattern in org_patterns:
                matches = re.finditer(pattern, text)
                for match in matches:
                    org_name = match.group(1).strip()
                    if len(org_name) > 2:  # Фильтруем слишком короткие
                        entities.append({
                            "text": org_name,
                            "type": "ORG",
                            "confidence": 0.75,
                            "source": "regex"
                        })
        
        if entity_types is None or "PERSON" in entity_types:
            for pattern in name_patterns:
                matches = re.finditer(pattern, text)
                for match in matches:
                    full_name = ' '.join(match.groups())
                    entities.append({
                        "text": full_name,
                        "type": "PERSON",
                        "confidence": 0.7,
                        "source": "regex"
                    })
        
        # Дедупликация
        seen = set()
        unique_entities = []
        for entity in entities:
            key = (entity["text"], entity["type"])
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)
        
        return unique_entities
    
    def extract_all(self, text: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Извлекает все типы информации из текста
        
        Args:
            text: Текст для анализа
            
        Returns:
            Dictionary with all extracted information:
            {
                "dates": [...],
                "amounts": [...],
                "entities": [...]
            }
        """
        return {
            "dates": self.extract_dates(text),
            "amounts": self.extract_amounts(text),
            "entities": self.extract_entities(text)
        }

