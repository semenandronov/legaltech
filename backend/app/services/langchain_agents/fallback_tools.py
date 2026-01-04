"""Fallback Tools - Phase 2.4 Implementation

This module provides rule-based fallback extractors and handlers
for critical fields when LLM-based extraction fails.

Features:
- Rule-based entity extraction
- Date parsing fallback
- Amount extraction fallback
- Pattern matching for common legal structures
"""
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)


class RuleBasedExtractor:
    """
    Rule-based extractor for critical fields.
    
    Used as fallback when LLM extraction fails or for
    validation of LLM outputs.
    """
    
    def __init__(self):
        """Initialize the extractor with patterns."""
        # Date patterns (Russian)
        self.date_patterns = [
            # DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY
            r'(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})',
            # DD Month YYYY (Russian)
            r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})',
            # "от DD.MM.YYYY" (date with preposition)
            r'от\s+(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})',
        ]
        
        # Amount patterns
        self.amount_patterns = [
            # 1 000 000 руб., 1 000 000 рублей
            r'(\d[\d\s,\.]*)\s*(руб\.?|рублей?|р\.?)',
            # 1,000,000.00 USD/EUR
            r'(\d[\d\s,\.]*)\s*(USD|EUR|долларов?|евро)',
            # сумма в размере X
            r'в\s+размере\s+(\d[\d\s,\.]*)\s*(руб\.?|рублей?)?',
        ]
        
        # INN patterns
        self.inn_pattern = r'ИНН\s*[:\s]*(\d{10,12})'
        
        # OGRN patterns
        self.ogrn_pattern = r'ОГРН\s*[:\s]*(\d{13,15})'
        
        # Case number patterns
        self.case_number_patterns = [
            r'дело\s*№?\s*([А-Яа-я]?\d{1,2}-\d+/\d{4})',
            r'№\s*([А-Яа-я]?\d{1,2}-\d+/\d{4})',
        ]
        
        # Russian months mapping
        self.month_map = {
            'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
            'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
            'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
        }
    
    def extract_dates(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract dates from text using rule-based patterns.
        
        Args:
            text: Text to extract from
            
        Returns:
            List of extracted dates
        """
        dates = []
        
        # Pattern 1: DD.MM.YYYY format
        for match in re.finditer(r'(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})', text):
            try:
                day, month, year = match.groups()
                date_str = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                # Validate date
                datetime.strptime(date_str, "%Y-%m-%d")
                dates.append({
                    "value": match.group(),
                    "normalized": date_str,
                    "position": match.start()
                })
            except ValueError:
                continue
        
        # Pattern 2: DD Month YYYY format
        pattern = r'(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})'
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                day, month_name, year = match.groups()
                month = self.month_map.get(month_name.lower())
                if month:
                    date_str = f"{year}-{str(month).zfill(2)}-{day.zfill(2)}"
                    dates.append({
                        "value": match.group(),
                        "normalized": date_str,
                        "position": match.start()
                    })
            except (ValueError, KeyError):
                continue
        
        # Remove duplicates
        seen = set()
        unique_dates = []
        for d in dates:
            if d["normalized"] not in seen:
                seen.add(d["normalized"])
                unique_dates.append(d)
        
        return unique_dates
    
    def extract_amounts(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract monetary amounts from text.
        
        Args:
            text: Text to extract from
            
        Returns:
            List of extracted amounts
        """
        amounts = []
        
        # Pattern for rubles
        rub_pattern = r'(\d[\d\s,\.]*)\s*(руб\.?|рублей?|р\.)'
        for match in re.finditer(rub_pattern, text, re.IGNORECASE):
            try:
                amount_str = match.group(1)
                # Clean amount string
                amount_str = re.sub(r'[\s,]', '', amount_str)
                amount = float(amount_str)
                amounts.append({
                    "value": match.group(),
                    "amount": amount,
                    "currency": "RUB",
                    "position": match.start()
                })
            except ValueError:
                continue
        
        # Pattern for USD/EUR
        foreign_pattern = r'(\d[\d\s,\.]*)\s*(USD|EUR|долларов?|евро)'
        for match in re.finditer(foreign_pattern, text, re.IGNORECASE):
            try:
                amount_str = match.group(1)
                amount_str = re.sub(r'[\s,]', '', amount_str)
                amount = float(amount_str)
                currency = "USD" if "USD" in match.group() or "доллар" in match.group().lower() else "EUR"
                amounts.append({
                    "value": match.group(),
                    "amount": amount,
                    "currency": currency,
                    "position": match.start()
                })
            except ValueError:
                continue
        
        return amounts
    
    def extract_inn(self, text: str) -> List[Dict[str, Any]]:
        """Extract INN (tax identification number) from text."""
        inns = []
        for match in re.finditer(self.inn_pattern, text, re.IGNORECASE):
            inn = match.group(1)
            # Validate INN length
            if len(inn) in [10, 12]:
                inns.append({
                    "value": inn,
                    "type": "individual" if len(inn) == 12 else "organization",
                    "position": match.start()
                })
        return inns
    
    def extract_ogrn(self, text: str) -> List[Dict[str, Any]]:
        """Extract OGRN (state registration number) from text."""
        ogrns = []
        for match in re.finditer(self.ogrn_pattern, text, re.IGNORECASE):
            ogrn = match.group(1)
            if len(ogrn) in [13, 15]:
                ogrns.append({
                    "value": ogrn,
                    "type": "individual" if len(ogrn) == 15 else "organization",
                    "position": match.start()
                })
        return ogrns
    
    def extract_case_numbers(self, text: str) -> List[Dict[str, Any]]:
        """Extract court case numbers from text."""
        case_numbers = []
        for pattern in self.case_number_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                case_numbers.append({
                    "value": match.group(1),
                    "position": match.start()
                })
        return case_numbers
    
    def extract_all(self, text: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract all supported entities from text.
        
        Args:
            text: Text to extract from
            
        Returns:
            Dictionary with all extracted entities
        """
        return {
            "dates": self.extract_dates(text),
            "amounts": self.extract_amounts(text),
            "inns": self.extract_inn(text),
            "ogrns": self.extract_ogrn(text),
            "case_numbers": self.extract_case_numbers(text)
        }


class FallbackHandler:
    """
    Handler for fallback logic when LLM extraction fails.
    
    Provides rule-based alternatives and partial results.
    """
    
    def __init__(self):
        """Initialize with rule-based extractor."""
        self.extractor = RuleBasedExtractor()
    
    def fallback_entity_extraction(
        self,
        text: str,
        failed_types: List[str] = None
    ) -> Dict[str, Any]:
        """
        Fallback entity extraction using rule-based patterns.
        
        Args:
            text: Text to extract from
            failed_types: List of entity types that failed
            
        Returns:
            Extracted entities
        """
        logger.info("Using fallback rule-based entity extraction")
        
        extracted = self.extractor.extract_all(text)
        
        result = {
            "entities": [],
            "method": "rule_based_fallback"
        }
        
        # Convert to entity format
        for date in extracted.get("dates", []):
            result["entities"].append({
                "type": "date",
                "value": date["value"],
                "normalized": date["normalized"],
                "confidence": 0.7  # Lower confidence for rule-based
            })
        
        for amount in extracted.get("amounts", []):
            result["entities"].append({
                "type": "amount",
                "value": amount["value"],
                "amount": amount["amount"],
                "currency": amount["currency"],
                "confidence": 0.7
            })
        
        for inn in extracted.get("inns", []):
            result["entities"].append({
                "type": "inn",
                "value": inn["value"],
                "entity_type": inn["type"],
                "confidence": 0.9  # High confidence for regex match
            })
        
        for ogrn in extracted.get("ogrns", []):
            result["entities"].append({
                "type": "ogrn",
                "value": ogrn["value"],
                "entity_type": ogrn["type"],
                "confidence": 0.9
            })
        
        for case_num in extracted.get("case_numbers", []):
            result["entities"].append({
                "type": "case_number",
                "value": case_num["value"],
                "confidence": 0.8
            })
        
        return result
    
    def fallback_timeline(
        self,
        text: str
    ) -> Dict[str, Any]:
        """
        Fallback timeline extraction using date patterns.
        
        Args:
            text: Text to extract from
            
        Returns:
            Basic timeline from extracted dates
        """
        logger.info("Using fallback rule-based timeline extraction")
        
        dates = self.extractor.extract_dates(text)
        
        events = []
        for i, date in enumerate(dates):
            # Extract context around the date
            pos = date["position"]
            context_start = max(0, pos - 100)
            context_end = min(len(text), pos + 100)
            context = text[context_start:context_end].strip()
            
            events.append({
                "event_id": f"event_{i+1}",
                "date": date["normalized"],
                "date_original": date["value"],
                "description": context,
                "confidence": 0.6,
                "method": "rule_based_fallback"
            })
        
        # Sort by date
        events.sort(key=lambda x: x["date"])
        
        return {
            "events": events,
            "total_events": len(events),
            "method": "rule_based_fallback"
        }
    
    def create_empty_result(
        self,
        agent_name: str,
        error_message: str
    ) -> Dict[str, Any]:
        """
        Create an empty but valid result for graceful degradation.
        
        Args:
            agent_name: Name of the failed agent
            error_message: Error that occurred
            
        Returns:
            Empty but structurally valid result
        """
        return {
            "status": "fallback",
            "agent_name": agent_name,
            "error": error_message,
            "result": None,
            "entities": [],
            "events": [],
            "facts": [],
            "risks": [],
            "discrepancies": [],
            "confidence": 0.0,
            "method": "empty_fallback"
        }


# Global instances
_extractor: Optional[RuleBasedExtractor] = None
_fallback_handler: Optional[FallbackHandler] = None


def get_rule_based_extractor() -> RuleBasedExtractor:
    """Get the global rule-based extractor."""
    global _extractor
    if _extractor is None:
        _extractor = RuleBasedExtractor()
    return _extractor


def get_fallback_handler() -> FallbackHandler:
    """Get the global fallback handler."""
    global _fallback_handler
    if _fallback_handler is None:
        _fallback_handler = FallbackHandler()
    return _fallback_handler

