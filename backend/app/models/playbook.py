"""Playbook models for contract compliance checking"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Boolean, Integer, DECIMAL
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class Playbook(Base):
    """
    Playbook model - набор правил для проверки контрактов.
    
    Позволяет автоматически проверять документы на соответствие 
    стандартам фирмы с генерацией redlines.
    
    Типы правил:
    - Red Lines: Абсолютные требования (нарушение = требует исправления)
    - Fallbacks: Можем договориться (предупреждение + рекомендация)
    - No-Gos: Полностью неприемлемо (отклонить документ)
    """
    __tablename__ = "playbooks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Основная информация
    name = Column(String(255), nullable=False, unique=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Тип контракта и юрисдикция
    contract_type = Column(String(100), nullable=False, index=True)  # nda, service_agreement, supply, license, employment, etc.
    jurisdiction = Column(String(100), nullable=True)  # RU, EU, US, EAEU, etc.
    
    # Видимость
    is_system = Column(Boolean, default=False)  # Системный playbook
    is_public = Column(Boolean, default=False)  # Публичный (доступен всем)
    
    # Владелец (для пользовательских playbooks)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Статистика использования
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    
    # Версионирование
    version = Column(Integer, default=1)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="playbooks")
    rules = relationship("PlaybookRule", back_populates="playbook", cascade="all, delete-orphan", order_by="PlaybookRule.priority")
    checks = relationship("PlaybookCheck", back_populates="playbook", cascade="all, delete-orphan")
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "contract_type": self.contract_type,
            "jurisdiction": self.jurisdiction,
            "is_system": self.is_system,
            "is_public": self.is_public,
            "user_id": self.user_id,
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "version": self.version,
            "rules_count": len(self.rules) if self.rules else 0,
            "rules": [r.to_dict() for r in self.rules] if self.rules else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def increment_usage(self):
        """Increment usage counter"""
        self.usage_count = (self.usage_count or 0) + 1
        self.last_used_at = datetime.utcnow()


class PlaybookRule(Base):
    """
    PlaybookRule model - отдельное правило в playbook.
    
    Типы правил (rule_type):
    - red_line: Абсолютное требование, нарушение требует исправления
    - fallback: Можно обсудить, но есть предпочтительный вариант
    - no_go: Полностью неприемлемо, документ отклоняется
    
    Типы условий (condition_type):
    - must_exist: Пункт должен присутствовать
    - must_not_exist: Пункт НЕ должен присутствовать
    - value_check: Проверка значения (сумма, процент)
    - duration_check: Проверка срока (минимум/максимум)
    - text_match: Текст должен содержать определённые фразы
    - text_not_match: Текст НЕ должен содержать определённые фразы
    """
    __tablename__ = "playbook_rules"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    playbook_id = Column(String, ForeignKey("playbooks.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Тип правила
    rule_type = Column(String(50), nullable=False)  # red_line, fallback, no_go
    
    # Категория пункта контракта
    clause_category = Column(String(100), nullable=False)  # confidentiality, termination, liability, indemnification, ip, data_protection, payment, etc.
    
    # Информация о правиле
    rule_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Условие проверки
    condition_type = Column(String(50), nullable=False)  # must_exist, must_not_exist, value_check, duration_check, text_match, text_not_match
    condition_config = Column(JSON, nullable=False, default=dict)
    # Примеры condition_config:
    # duration_check: {"min_duration": "3 years", "max_duration": null, "operator": ">="}
    # value_check: {"min_value": 100000, "max_value": null, "currency": "RUB"}
    # text_match: {"patterns": ["shall provide notice", "must notify"], "match_type": "any"}
    # text_not_match: {"patterns": ["unlimited liability", "waive all rights"]}
    
    # Промпт для LLM для извлечения и проверки
    extraction_prompt = Column(Text, nullable=True)  # Промпт для извлечения пункта
    validation_prompt = Column(Text, nullable=True)  # Промпт для проверки условия
    
    # Шаблон для исправления
    suggested_clause_template = Column(Text, nullable=True)  # Рекомендуемый текст пункта
    
    # Альтернативные варианты (для fallback правил)
    fallback_options = Column(JSON, nullable=True)
    # Пример: [{"option": "2 years", "acceptable": true, "priority": 1}, {"option": "1 year", "acceptable": false}]
    
    # Приоритет (для сортировки и определения важности)
    priority = Column(Integer, default=0)  # 0 - обычный, 1-10 - повышенный
    
    # Severity для отображения в UI
    severity = Column(String(20), default="medium")  # low, medium, high, critical
    
    # Активно ли правило
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    playbook = relationship("Playbook", back_populates="rules")
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "playbook_id": self.playbook_id,
            "rule_type": self.rule_type,
            "clause_category": self.clause_category,
            "rule_name": self.rule_name,
            "description": self.description,
            "condition_type": self.condition_type,
            "condition_config": self.condition_config or {},
            "extraction_prompt": self.extraction_prompt,
            "validation_prompt": self.validation_prompt,
            "suggested_clause_template": self.suggested_clause_template,
            "fallback_options": self.fallback_options or [],
            "priority": self.priority,
            "severity": self.severity,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PlaybookCheck(Base):
    """
    PlaybookCheck model - результат проверки документа против playbook.
    
    Статусы (overall_status):
    - compliant: Документ полностью соответствует
    - non_compliant: Есть нарушения red_line или no_go
    - needs_review: Есть fallback issues, требуется ручная проверка
    - in_progress: Проверка в процессе
    - failed: Ошибка при проверке
    """
    __tablename__ = "playbook_checks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Связи
    playbook_id = Column(String, ForeignKey("playbooks.id", ondelete="SET NULL"), nullable=True, index=True)
    document_id = Column(String, nullable=False, index=True)  # ID документа (file_id)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Информация о документе на момент проверки
    document_name = Column(String(500), nullable=True)
    document_hash = Column(String(64), nullable=True)  # SHA256 hash для проверки изменений
    
    # Общий результат
    overall_status = Column(String(50), nullable=False, default="in_progress")  # compliant, non_compliant, needs_review, in_progress, failed
    compliance_score = Column(DECIMAL(5, 2), nullable=True)  # 0.00 - 100.00 (процент соответствия)
    
    # Счётчики нарушений
    red_line_violations = Column(Integer, default=0)
    fallback_issues = Column(Integer, default=0)
    no_go_violations = Column(Integer, default=0)
    passed_rules = Column(Integer, default=0)
    
    # Детальные результаты проверки каждого правила
    results = Column(JSON, nullable=False, default=list)
    # Формат: [
    #   {
    #     "rule_id": "...",
    #     "rule_name": "...",
    #     "rule_type": "red_line",
    #     "status": "violation|passed|not_found|error",
    #     "found_text": "Текст найденного пункта",
    #     "location": {"page": 3, "section": "4.2"},
    #     "issue_description": "Описание проблемы",
    #     "suggested_fix": "Предлагаемое исправление",
    #     "confidence": 0.95
    #   }
    # ]
    
    # Сгенерированные redlines
    redlines = Column(JSON, nullable=True)
    # Формат: [
    #   {
    #     "rule_id": "...",
    #     "original_text": "Исходный текст",
    #     "suggested_text": "Предлагаемый текст",
    #     "location": {"page": 3, "section": "4.2"},
    #     "change_type": "replace|add|remove"
    #   }
    # ]
    
    # Извлечённые пункты документа (кэш для ускорения)
    extracted_clauses = Column(JSON, nullable=True)
    
    # Ошибка (если failed)
    error_message = Column(Text, nullable=True)
    
    # Время выполнения
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    processing_time_seconds = Column(Integer, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    playbook = relationship("Playbook", back_populates="checks")
    case = relationship("Case", backref="playbook_checks")
    user = relationship("User", backref="playbook_checks")
    
    def to_dict(self, include_details: bool = True):
        """Convert to dictionary for API responses"""
        result = {
            "id": self.id,
            "playbook_id": self.playbook_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "case_id": self.case_id,
            "user_id": self.user_id,
            "overall_status": self.overall_status,
            "compliance_score": float(self.compliance_score) if self.compliance_score else None,
            "red_line_violations": self.red_line_violations,
            "fallback_issues": self.fallback_issues,
            "no_go_violations": self.no_go_violations,
            "passed_rules": self.passed_rules,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "processing_time_seconds": self.processing_time_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        
        if include_details:
            result["results"] = self.results or []
            result["redlines"] = self.redlines or []
            result["error_message"] = self.error_message
        
        return result
    
    def calculate_compliance_score(self):
        """Calculate compliance score based on results"""
        if not self.results:
            return None
        
        total_rules = len(self.results)
        if total_rules == 0:
            return 100.0
        
        passed = sum(1 for r in self.results if r.get("status") == "passed")
        return round((passed / total_rules) * 100, 2)


# Константы для типов контрактов
CONTRACT_TYPES = [
    {"name": "nda", "display_name": "NDA (Соглашение о неразглашении)"},
    {"name": "service_agreement", "display_name": "Договор оказания услуг"},
    {"name": "supply_contract", "display_name": "Договор поставки"},
    {"name": "license_agreement", "display_name": "Лицензионное соглашение"},
    {"name": "employment_contract", "display_name": "Трудовой договор"},
    {"name": "lease_agreement", "display_name": "Договор аренды"},
    {"name": "loan_agreement", "display_name": "Договор займа"},
    {"name": "agency_agreement", "display_name": "Агентский договор"},
    {"name": "distribution_agreement", "display_name": "Дистрибьюторский договор"},
    {"name": "franchise_agreement", "display_name": "Договор франчайзинга"},
    {"name": "joint_venture", "display_name": "Договор о совместной деятельности"},
    {"name": "sha", "display_name": "Акционерное соглашение (SHA)"},
    {"name": "spa", "display_name": "Договор купли-продажи акций (SPA)"},
    {"name": "other", "display_name": "Другой тип договора"},
]

# Константы для категорий пунктов
CLAUSE_CATEGORIES = [
    {"name": "confidentiality", "display_name": "Конфиденциальность"},
    {"name": "termination", "display_name": "Расторжение договора"},
    {"name": "liability", "display_name": "Ответственность"},
    {"name": "indemnification", "display_name": "Возмещение убытков"},
    {"name": "intellectual_property", "display_name": "Интеллектуальная собственность"},
    {"name": "data_protection", "display_name": "Защита данных"},
    {"name": "payment", "display_name": "Оплата"},
    {"name": "warranties", "display_name": "Гарантии"},
    {"name": "force_majeure", "display_name": "Форс-мажор"},
    {"name": "dispute_resolution", "display_name": "Разрешение споров"},
    {"name": "governing_law", "display_name": "Применимое право"},
    {"name": "assignment", "display_name": "Уступка прав"},
    {"name": "non_compete", "display_name": "Неконкуренция"},
    {"name": "non_solicitation", "display_name": "Непереманивание"},
    {"name": "audit_rights", "display_name": "Право на аудит"},
    {"name": "insurance", "display_name": "Страхование"},
    {"name": "compliance", "display_name": "Соответствие требованиям"},
    {"name": "change_of_control", "display_name": "Смена контроля"},
    {"name": "notice", "display_name": "Уведомления"},
    {"name": "entire_agreement", "display_name": "Полнота соглашения"},
    {"name": "amendments", "display_name": "Изменения и дополнения"},
    {"name": "other", "display_name": "Другое"},
]

# Константы для юрисдикций
JURISDICTIONS = [
    {"name": "RU", "display_name": "Россия"},
    {"name": "EAEU", "display_name": "ЕАЭС"},
    {"name": "EU", "display_name": "Европейский Союз"},
    {"name": "US", "display_name": "США"},
    {"name": "UK", "display_name": "Великобритания"},
    {"name": "CN", "display_name": "Китай"},
    {"name": "INTERNATIONAL", "display_name": "Международное"},
]

