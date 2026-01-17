"""Initialize system templates for Playbooks and Workflows"""
from sqlalchemy.orm import Session
from app.models.playbook import Playbook, PlaybookRule
from app.models.workflow import WorkflowDefinition, SYSTEM_WORKFLOW_TEMPLATES
import logging

logger = logging.getLogger(__name__)


def init_system_playbooks(db: Session):
    """Initialize system playbooks"""
    
    # Check if already initialized
    existing = db.query(Playbook).filter(Playbook.is_system == True).first()
    if existing:
        logger.info("System playbooks already initialized")
        return
    
    # NDA Playbook
    nda_playbook = Playbook(
        name="system_nda_standard",
        display_name="Стандартный NDA Playbook",
        description="Набор правил для проверки соглашений о неразглашении",
        contract_type="nda",
        jurisdiction="RU",
        is_system=True,
        is_public=True
    )
    db.add(nda_playbook)
    db.flush()
    
    # NDA Rules
    nda_rules = [
        PlaybookRule(
            playbook_id=nda_playbook.id,
            rule_type="red_line",
            clause_category="confidentiality",
            rule_name="Определение конфиденциальной информации",
            description="Договор должен содержать чёткое определение конфиденциальной информации",
            condition_type="must_exist",
            condition_config={"required_patterns": ["конфиденциальная информация", "confidential information"]},
            suggested_clause_template="«Конфиденциальная информация» означает любую информацию, раскрытую одной Стороной другой Стороне, которая помечена как конфиденциальная или которая по своей природе должна рассматриваться как конфиденциальная.",
            priority=10,
            severity="high"
        ),
        PlaybookRule(
            playbook_id=nda_playbook.id,
            rule_type="red_line",
            clause_category="confidentiality",
            rule_name="Срок конфиденциальности",
            description="Срок обязательства о неразглашении должен быть не менее 3 лет",
            condition_type="duration_check",
            condition_config={"min_duration": "3 years"},
            suggested_clause_template="Обязательства по сохранению конфиденциальности действуют в течение 5 (пяти) лет с даты раскрытия информации.",
            priority=8,
            severity="medium"
        ),
        PlaybookRule(
            playbook_id=nda_playbook.id,
            rule_type="fallback",
            clause_category="liability",
            rule_name="Ограничение ответственности",
            description="Должно быть указание на ответственность за нарушение конфиденциальности",
            condition_type="must_exist",
            condition_config={"required_patterns": ["ответственность", "убытки", "возмещение"]},
            fallback_options=[
                {"option": "Прямые убытки", "acceptable": True},
                {"option": "Без ограничения", "acceptable": False}
            ],
            priority=5,
            severity="medium"
        ),
        PlaybookRule(
            playbook_id=nda_playbook.id,
            rule_type="no_go",
            clause_category="confidentiality",
            rule_name="Запрет неограниченного раскрытия",
            description="NDA не должен содержать права на неограниченное раскрытие третьим лицам",
            condition_type="text_not_match",
            condition_config={"patterns": ["неограниченное право передачи", "любым третьим лицам без согласия"]},
            priority=10,
            severity="critical"
        ),
    ]
    
    for rule in nda_rules:
        db.add(rule)
    
    # Service Agreement Playbook
    service_playbook = Playbook(
        name="system_service_agreement",
        display_name="Договор оказания услуг",
        description="Набор правил для проверки договоров оказания услуг",
        contract_type="service_agreement",
        jurisdiction="RU",
        is_system=True,
        is_public=True
    )
    db.add(service_playbook)
    db.flush()
    
    service_rules = [
        PlaybookRule(
            playbook_id=service_playbook.id,
            rule_type="red_line",
            clause_category="payment",
            rule_name="Условия оплаты",
            description="Договор должен содержать чёткие условия оплаты",
            condition_type="must_exist",
            condition_config={"required_patterns": ["оплата", "вознаграждение", "стоимость услуг"]},
            priority=10,
            severity="high"
        ),
        PlaybookRule(
            playbook_id=service_playbook.id,
            rule_type="red_line",
            clause_category="termination",
            rule_name="Право на расторжение",
            description="Должно быть предусмотрено право на односторонний отказ",
            condition_type="must_exist",
            condition_config={"required_patterns": ["расторжение", "отказ", "прекращение договора"]},
            suggested_clause_template="Любая Сторона вправе отказаться от исполнения настоящего Договора, уведомив другую Сторону не менее чем за 30 (тридцать) дней.",
            priority=8,
            severity="high"
        ),
        PlaybookRule(
            playbook_id=service_playbook.id,
            rule_type="fallback",
            clause_category="liability",
            rule_name="Ограничение ответственности",
            description="Ответственность должна быть ограничена разумными пределами",
            condition_type="must_exist",
            condition_config={"required_patterns": ["ответственность ограничивается", "не превышает"]},
            fallback_options=[
                {"option": "Сумма договора", "acceptable": True},
                {"option": "Годовая сумма", "acceptable": True},
                {"option": "Без ограничений", "acceptable": False}
            ],
            priority=6,
            severity="medium"
        ),
        PlaybookRule(
            playbook_id=service_playbook.id,
            rule_type="no_go",
            clause_category="liability",
            rule_name="Запрет безлимитной ответственности",
            description="Договор не должен предусматривать неограниченную ответственность",
            condition_type="text_not_match",
            condition_config={"patterns": ["полная ответственность без ограничений", "unlimited liability"]},
            priority=10,
            severity="critical"
        ),
    ]
    
    for rule in service_rules:
        db.add(rule)
    
    db.commit()
    logger.info("System playbooks initialized: NDA, Service Agreement")


def init_system_workflows(db: Session):
    """Initialize system workflow definitions"""
    
    # Check if already initialized
    existing = db.query(WorkflowDefinition).filter(WorkflowDefinition.is_system == True).first()
    if existing:
        logger.info("System workflows already initialized")
        return
    
    for template in SYSTEM_WORKFLOW_TEMPLATES:
        definition = WorkflowDefinition(
            name=template["name"],
            display_name=template["display_name"],
            description=template["description"],
            category=template["category"],
            available_tools=template["available_tools"],
            default_plan=template.get("default_plan"),
            is_system=True,
            is_public=True
        )
        db.add(definition)
    
    db.commit()
    logger.info(f"System workflows initialized: {len(SYSTEM_WORKFLOW_TEMPLATES)} templates")


def init_all_system_templates(db: Session):
    """Initialize all system templates"""
    try:
        init_system_playbooks(db)
        init_system_workflows(db)
        logger.info("All system templates initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize system templates: {e}", exc_info=True)
        db.rollback()
        raise

