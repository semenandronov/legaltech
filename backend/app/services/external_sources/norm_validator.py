"""Валидатор актуальности норм права"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from .pravo_gov_source import PravoGovSource
import logging
import re

logger = logging.getLogger(__name__)


class NormValidator:
    """
    Проверяет актуальность норм права.
    
    Поддерживает:
    - Проверка, не утратила ли статья силу
    - Поиск последней редакции
    - Предупреждение о планируемых изменениях
    """
    
    def __init__(self):
        """Initialize norm validator"""
        self.pravo_source = None
    
    async def initialize(self) -> bool:
        """Initialize validator with pravo.gov.ru source"""
        try:
            self.pravo_source = PravoGovSource()
            await self.pravo_source.ensure_initialized()
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize NormValidator: {e}")
            return False
    
    async def validate_norm(
        self,
        code: str,
        article: str,
        part: Optional[str] = None,
        paragraph: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Проверяет актуальность нормы
        
        Args:
            code: Название кодекса (ГК, АПК, и т.д.)
            article: Номер статьи
            part: Номер части (опционально)
            paragraph: Номер пункта (опционально)
        
        Returns:
            Словарь с результатами проверки:
            {
                "is_valid": bool,  # Действует ли норма
                "is_current": bool,  # Является ли текущей редакцией
                "last_revision_date": Optional[datetime],  # Дата последней редакции
                "expiry_date": Optional[datetime],  # Дата утраты силы (если есть)
                "warnings": List[str],  # Предупреждения
                "suggestions": List[str]  # Рекомендации
            }
        """
        if not self.pravo_source:
            await self.initialize()
        
        result = {
            "is_valid": True,  # По умолчанию считаем, что норма действует
            "is_current": True,  # По умолчанию считаем, что это текущая редакция
            "last_revision_date": None,
            "expiry_date": None,
            "warnings": [],
            "suggestions": []
        }
        
        try:
            # Пытаемся получить статью с pravo.gov.ru
            article_result = await self.pravo_source._get_article_direct(
                code=code,
                article=article,
                part=part,
                paragraph=paragraph
            )
            
            if article_result:
                # Проверяем метаданные на наличие информации об актуальности
                metadata = article_result.metadata
                
                # Если есть дата последней редакции
                if "last_revision_date" in metadata:
                    result["last_revision_date"] = metadata["last_revision_date"]
                
                # Если есть дата утраты силы
                if "expiry_date" in metadata:
                    result["expiry_date"] = metadata["expiry_date"]
                    result["is_valid"] = False
                    result["warnings"].append(f"Статья утратила силу с {metadata['expiry_date']}")
                else:
                    # Проверяем текст статьи на наличие отметок об утрате силы
                    content = article_result.content.lower()
                    
                    # Ищем фразы об утрате силы
                    expiry_patterns = [
                        r'утратил.*?силу.*?(\d{2}\.\d{2}\.\d{4})',
                        r'не.*?действует.*?с.*?(\d{2}\.\d{2}\.\d{4})',
                        r'исключен.*?(\d{2}\.\d{2}\.\d{4})',
                    ]
                    
                    for pattern in expiry_patterns:
                        match = re.search(pattern, content, re.IGNORECASE)
                        if match:
                            try:
                                expiry_date = datetime.strptime(match.group(1), "%d.%m.%Y")
                                result["expiry_date"] = expiry_date
                                result["is_valid"] = False
                                result["warnings"].append(f"Статья утратила силу с {match.group(1)}")
                                break
                            except ValueError:
                                continue
            else:
                # Не удалось получить статью - возможно, она не существует
                result["warnings"].append(f"Не удалось проверить актуальность статьи {article} {code}")
                result["suggestions"].append("Проверьте номер статьи и кодекса")
            
        except Exception as e:
            logger.error(f"Error validating norm: {e}", exc_info=True)
            result["warnings"].append(f"Ошибка при проверке актуальности: {str(e)}")
        
        return result
    
    async def check_for_updates(
        self,
        code: str,
        article: str,
        known_revision_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Проверяет наличие обновлений нормы
        
        Args:
            code: Название кодекса
            article: Номер статьи
            known_revision_date: Известная дата редакции для сравнения
        
        Returns:
            Словарь с информацией об обновлениях
        """
        result = {
            "has_updates": False,
            "latest_revision_date": None,
            "changes": []
        }
        
        try:
            validation_result = await self.validate_norm(code, article)
            
            if validation_result["last_revision_date"]:
                result["latest_revision_date"] = validation_result["last_revision_date"]
                
                if known_revision_date:
                    if validation_result["last_revision_date"] > known_revision_date:
                        result["has_updates"] = True
                        result["changes"].append(
                            f"Норма была изменена после {known_revision_date.strftime('%d.%m.%Y')}"
                        )
        except Exception as e:
            logger.error(f"Error checking for updates: {e}", exc_info=True)
        
        return result

