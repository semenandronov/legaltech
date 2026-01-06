"""Tabular Review Verifier service for validating cell extractions"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models.tabular_review import TabularCell, TabularColumn
from app.models.case import File
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class VerificationResult:
    """Result of cell verification"""
    def __init__(
        self,
        is_valid: bool,
        issues: List[str],
        suggested_status: str
    ):
        self.is_valid = is_valid
        self.issues = issues
        self.suggested_status = suggested_status


class TabularReviewVerifier:
    """Service for verifying tabular cell extractions"""
    
    def __init__(self, db: Session):
        """Initialize verifier"""
        self.db = db
    
    def verify_cell(
        self,
        cell: TabularCell,
        column: TabularColumn,
        file: Optional[File] = None
    ) -> VerificationResult:
        """
        Verify a cell extraction
        
        Args:
            cell: TabularCell to verify
            column: TabularColumn definition
            file: Optional File object for quote verification
        
        Returns:
            VerificationResult with validation status and issues
        """
        issues = []
        is_valid = True
        
        # Check if cell has value
        if not cell.cell_value or cell.cell_value.strip() == "":
            if cell.status not in ["empty", "n_a"]:
                issues.append("Cell value is empty but status is not 'empty' or 'n_a'")
                is_valid = False
            return VerificationResult(
                is_valid=is_valid,
                issues=issues,
                suggested_status="empty" if not cell.cell_value else "n_a"
            )
        
        # Verify quote is contained in document (if file provided)
        if file and cell.verbatim_extract:
            if not self._verify_quote_in_document(cell.verbatim_extract, file):
                issues.append("Verbatim extract not found in document text")
                is_valid = False
        
        # Verify value can be derived from quote (for numbers/dates)
        if cell.verbatim_extract and column.column_type in ['currency', 'number', 'date']:
            if not self._verify_value_from_quote(cell.cell_value, cell.verbatim_extract, column.column_type):
                issues.append(f"Value '{cell.cell_value}' cannot be derived from quote for {column.column_type} type")
                is_valid = False
        
        # Validate against hard rules based on column type
        validation_issues = self._validate_hard_rules(cell.cell_value, column.column_type)
        issues.extend(validation_issues)
        if validation_issues:
            is_valid = False
        
        # Check normalized_value consistency
        if cell.normalized_value and column.column_type in ['date', 'currency', 'number', 'yes_no']:
            if not self._verify_normalization(cell.cell_value, cell.normalized_value, column.column_type):
                issues.append("Normalized value is inconsistent with cell_value")
                is_valid = False
        
        # Determine suggested status
        if not is_valid:
            if cell.status == "conflict":
                suggested_status = "conflict"
            elif cell.confidence_score and cell.confidence_score < 0.7:
                suggested_status = "pending"  # Low confidence, needs review
            else:
                suggested_status = "completed"  # Has issues but not critical
        else:
            suggested_status = "completed" if cell.status != "conflict" else "conflict"
        
        return VerificationResult(
            is_valid=is_valid,
            issues=issues,
            suggested_status=suggested_status
        )
    
    def _verify_quote_in_document(self, quote: str, file: File) -> bool:
        """Verify that quote text is contained in document"""
        if not file.original_text:
            return False
        
        # Normalize both texts for comparison (remove extra whitespace)
        quote_normalized = re.sub(r'\s+', ' ', quote.strip())
        doc_normalized = re.sub(r'\s+', ' ', file.original_text)
        
        # Check if quote is in document (case-insensitive for flexibility)
        return quote_normalized.lower() in doc_normalized.lower()
    
    def _verify_value_from_quote(
        self,
        value: str,
        quote: str,
        column_type: str
    ) -> bool:
        """Verify that value can be derived from quote"""
        if not value or not quote:
            return False
        
        if column_type == 'currency':
            # Extract numbers from both
            value_numbers = re.findall(r'[\d.,]+', value.replace(' ', ''))
            quote_numbers = re.findall(r'[\d.,]+', quote.replace(' ', ''))
            if not value_numbers or not quote_numbers:
                return False
            # Compare first number (main amount)
            try:
                val_num = float(value_numbers[0].replace(',', '.'))
                quote_num = float(quote_numbers[0].replace(',', '.'))
                return abs(val_num - quote_num) < 0.01  # Allow small floating point differences
            except:
                return False
        
        elif column_type == 'number':
            # Extract numbers from both
            value_numbers = re.findall(r'[\d.,]+', value.replace(' ', ''))
            quote_numbers = re.findall(r'[\d.,]+', quote.replace(' ', ''))
            if not value_numbers or not quote_numbers:
                return False
            try:
                val_num = float(value_numbers[0].replace(',', '.'))
                quote_num = float(quote_numbers[0].replace(',', '.'))
                return abs(val_num - quote_num) < 0.01
            except:
                return False
        
        elif column_type == 'date':
            # For dates, check if value appears in quote (normalized format)
            value_normalized = value.strip()
            quote_normalized = quote.strip()
            # Check if date value appears in quote
            return value_normalized in quote_normalized or value_normalized.replace('-', '.') in quote_normalized
        
        return True  # For other types, assume valid
    
    def _validate_hard_rules(self, value: str, column_type: str) -> List[str]:
        """Validate value against hard business rules"""
        issues = []
        
        if not value or value.strip() == "":
            return issues
        
        if column_type == 'date':
            # Try to parse as date
            try:
                from app.services.date_validator import parse_and_normalize_date
                normalized = parse_and_normalize_date(value)
                datetime.strptime(normalized, "%Y-%m-%d")
            except Exception as e:
                issues.append(f"Invalid date format: {value}")
        
        elif column_type == 'currency':
            # Check if it's a valid number
            try:
                cleaned = re.sub(r'[^\d.,]', '', value.replace(' ', '').replace(',', '.'))
                float(cleaned)
            except:
                issues.append(f"Invalid currency format: {value}")
        
        elif column_type == 'number':
            # Check if it's a valid number
            try:
                cleaned = value.replace(' ', '').replace(',', '.')
                float(cleaned)
            except:
                issues.append(f"Invalid number format: {value}")
        
        elif column_type == 'yes_no':
            # Check if it's a valid yes/no value
            value_lower = value.lower().strip()
            valid_values = ['yes', 'no', 'unknown', 'да', 'нет']
            if value_lower not in valid_values and value_lower not in ['true', 'false', '1', '0']:
                issues.append(f"Invalid yes/no value: {value}")
        
        # Add INN validation if needed (could be detected from column label)
        # This is a placeholder - actual INN validation would check for 10/12 digits
        
        return issues
    
    def _verify_normalization(
        self,
        cell_value: str,
        normalized_value: str,
        column_type: str
    ) -> bool:
        """Verify that normalized_value is consistent with cell_value"""
        if not normalized_value:
            return True  # No normalization is fine
        
        try:
            if column_type == 'date':
                # Both should be valid dates
                from app.services.date_validator import parse_and_normalize_date
                norm_from_cell = parse_and_normalize_date(cell_value)
                return norm_from_cell == normalized_value
            
            elif column_type in ['currency', 'number']:
                # Both should represent the same number
                cell_clean = re.sub(r'[^\d.,]', '', cell_value.replace(' ', '').replace(',', '.'))
                norm_clean = normalized_value.replace(' ', '').replace(',', '.')
                try:
                    cell_num = float(cell_clean)
                    norm_num = float(norm_clean)
                    return abs(cell_num - norm_num) < 0.01
                except:
                    return False
            
            elif column_type == 'yes_no':
                # Both should normalize to same value
                from app.services.tabular_review_models import validate_yes_no
                norm_from_cell = validate_yes_no(cell_value)
                return norm_from_cell == normalized_value
            
        except Exception as e:
            logger.warning(f"Error verifying normalization: {e}")
            return False
        
        return True

