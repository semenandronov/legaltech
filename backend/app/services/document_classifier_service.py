"""Service for automatic document classification during upload"""
from typing import Dict, Any, Optional
from app.services.llm_factory import create_llm
from app.services.langchain_parsers import DocumentClassificationModel
from app.services.yandex_classifier import YandexDocumentClassifier
from app.config import config
from langchain_core.prompts import ChatPromptTemplate
import logging

logger = logging.getLogger(__name__)

# Порог уверенности для автоматической проверки
CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.75

# Фиксированный набор типов документов (26 типов)
DOCUMENT_TYPES = [
    # Процессуальные документы участников
    "statement_of_claim",      # Исковое заявление
    "application",             # Заявление
    "response_to_claim",       # Отзыв на иск
    "counterclaim",            # Встречный иск
    "motion",                  # Ходатайство
    "appeal",                  # Апелляционная жалоба
    "cassation",               # Кассационная жалоба
    "supervisory_appeal",      # Надзорная жалоба
    "protocol_remarks",        # Замечания на протокол
    "settlement_agreement",    # Мировое соглашение
    # Судебные акты
    "court_order",             # Судебный приказ
    "court_decision",          # Решение
    "court_ruling",            # Определение
    "court_resolution",        # Постановление
    # Доказательства
    "contract",                # Договор
    "act",                     # Акт
    "certificate",             # Справка
    "correspondence",          # Деловая переписка
    "electronic_document",     # Электронный документ
    "protocol",                # Протокол
    "expert_opinion",          # Заключение эксперта
    "specialist_consultation", # Консультация специалиста
    "witness_statement",       # Показания свидетеля
    "audio_recording",         # Аудиозапись
    "video_recording",         # Видеозапись
    "physical_evidence",       # Вещественное доказательство
    # Прочие
    "other"                    # Другое
]


class DocumentClassifierService:
    """Service for classifying documents during upload"""
    
    def __init__(self):
        self.yandex_classifier = None
        self.llm = None
        self._init_classifiers()
    
    def _init_classifiers(self):
        """Initialize classifiers (Yandex preferred, GigaChat fallback)"""
        # Пытаемся использовать Yandex AI Studio классификатор
        if (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN) and config.YANDEX_AI_STUDIO_CLASSIFIER_ID:
            try:
                self.yandex_classifier = YandexDocumentClassifier()
                if self.yandex_classifier.is_available():
                    logger.info("✅ Using Yandex AI Studio classifier for upload classification")
                    return
            except Exception as e:
                logger.warning(f"Failed to initialize Yandex classifier: {e}, using GigaChat fallback")
        
        # Fallback to GigaChat LLM
        try:
            self.llm = create_llm(temperature=0.1)
            logger.info("✅ Using GigaChat LLM for document classification")
        except Exception as e:
            logger.warning(f"Failed to initialize GigaChat for classification: {e}, classification will use default values")
            self.llm = None
    
    def classify_document(
        self,
        text: str,
        filename: Optional[str] = None,
        case_context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Classify a document
        
        Args:
            text: Document text (will be truncated to 15000 chars)
            filename: Optional filename for context
            case_context: Optional case context
            
        Returns:
            Dictionary with doc_type, tags, confidence, needs_human_review
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for classification")
            return self._default_classification("Empty document")
        
        # Ограничиваем текст для экономии токенов
        prompt_text = text[:15000]
        
        try:
            # Используем Yandex если доступен
            if self.yandex_classifier:
                return self._classify_with_yandex(prompt_text, filename)
            
            # Fallback to GigaChat
            if self.llm:
                return self._classify_with_llm(prompt_text, filename, case_context)
            
            # Если ни один классификатор не доступен, возвращаем дефолтную классификацию
            logger.warning("No classifier available, using default classification")
            return self._default_classification("No classifier available")
            
        except Exception as e:
            logger.warning(f"Error classifying document: {e}", exc_info=True)
            return self._default_classification(f"Classification error: {str(e)}")
    
    def _classify_with_yandex(self, text: str, filename: Optional[str]) -> Dict[str, Any]:
        """Classify using Yandex AI Studio"""
        try:
            # Используем типы документов из нашего списка
            yandex_result = self.yandex_classifier.classify(
                text=text,
                classes=DOCUMENT_TYPES
            )
            
            doc_type = yandex_result["type"]
            confidence = yandex_result["confidence"]
            
            # Определяем теги на основе типа
            tags = self._get_tags_for_type(doc_type)
            
            # Определяем нужна ли ручная проверка
            needs_human_review = confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD
            
            return {
                "doc_type": doc_type,
                "tags": tags,
                "confidence": confidence,
                "needs_human_review": needs_human_review,
                "reasoning": f"Классифицировано через Yandex AI Studio. Уверенность: {confidence:.0%}",
                "classifier": "yandex"
            }
        except Exception as e:
            logger.warning(f"Yandex classification failed: {e}, falling back to GigaChat")
            if self.llm:
                return self._classify_with_llm(text, filename, None)
            raise
    
    def _classify_with_llm(
        self,
        text: str,
        filename: Optional[str],
        case_context: Optional[str]
    ) -> Dict[str, Any]:
        """Classify using GigaChat LLM with structured output"""
        system_prompt = f"""Ты эксперт по классификации юридических документов.

Твоя задача: определить тип документа, теги и уверенность классификации.

Доступные типы документов (26 типов):

1. ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ УЧАСТНИКОВ:
   - statement_of_claim - Исковое заявление (основное обращение в спорах, вытекающих из гражданских правоотношений)
   - application - Заявление (используется в делах без спора об объекте: административные споры, банкротство)
   - response_to_claim - Отзыв на иск (ответ на исковое заявление)
   - counterclaim - Встречный иск (иск ответчика к истцу в рамках того же дела)
   - motion - Ходатайство (просьбы к суду о совершении процессуальных действий)
   - appeal - Апелляционная жалоба (для обжалования судебных актов)
   - cassation - Кассационная жалоба
   - supervisory_appeal - Надзорная жалоба
   - protocol_remarks - Замечания на протокол судебного заседания
   - settlement_agreement - Мировое соглашение

2. СУДЕБНЫЕ АКТЫ (ДОКУМЕНТЫ СУДА):
   - court_order - Судебный приказ (выносится без судебного заседания по простым требованиям)
   - court_decision - Решение (основной акт, разрешающий дело по существу)
   - court_ruling - Определение (акты по вопросам, возникающим в ходе процесса)
   - court_resolution - Постановление (выносится в апелляционной и кассационной инстанциях)

3. ДОКАЗАТЕЛЬСТВА:
   - contract - Договор
   - act - Акт
   - certificate - Справка
   - correspondence - Деловая переписка
   - electronic_document - Электронный документ
   - protocol - Протокол
   - expert_opinion - Заключение эксперта
   - specialist_consultation - Консультация специалиста
   - witness_statement - Показания свидетеля
   - audio_recording - Аудиозапись
   - video_recording - Видеозапись
   - physical_evidence - Вещественное доказательство

4. ПРОЧИЕ:
   - other - Другое (для документов, не подходящих под вышеперечисленные категории)

Верни структурированный ответ с полями:
- doc_type: один из доступных типов
- tags: массив тегов (например, ["юридический", "договорной"])
- confidence: уверенность от 0.0 до 1.0

Будь точным и объективным. Если уверенность < 0.75, документ потребует ручной проверки."""

        user_prompt = f"""Классифицируй следующий документ:

Файл: {filename or 'Неизвестно'}

Текст документа:
{text[:15000]}

Определи тип документа, добавь релевантные теги и укажи уверенность классификации."""

        try:
            # Пытаемся использовать structured output
            structured_llm = self.llm.with_structured_output(DocumentClassificationModel)
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human", user_prompt)
            ])
            chain = prompt | structured_llm
            classification = chain.invoke({})
            
            # Преобразуем в нужный формат
            confidence = float(classification.confidence) if isinstance(classification.confidence, (int, float)) else 0.5
            needs_human_review = confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD
            
            return {
                "doc_type": classification.doc_type,
                "tags": classification.key_topics or [],
                "confidence": confidence,
                "needs_human_review": needs_human_review,
                "reasoning": classification.reasoning or "Классифицировано через GigaChat LLM",
                "classifier": "gigachat"
            }
        except Exception as e:
            logger.warning(f"Structured output failed: {e}, using JSON parsing")
            # Fallback к парсингу JSON
            from app.services.langchain_parsers import ParserService
            try:
                prompt = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("human", user_prompt)
                ])
                chain = prompt | self.llm
                response = chain.invoke({})
                response_text = response.content if hasattr(response, 'content') else str(response)
                classification = ParserService.parse_document_classification(response_text)
                
                confidence = float(classification.confidence) if isinstance(classification.confidence, (int, float)) else 0.5
                needs_human_review = confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD
                
                return {
                    "doc_type": classification.doc_type,
                    "tags": classification.key_topics or [],
                    "confidence": confidence,
                    "needs_human_review": needs_human_review,
                    "reasoning": classification.reasoning or "Классифицировано через GigaChat LLM",
                    "classifier": "gigachat"
                }
            except Exception as parse_error:
                logger.warning(f"JSON parsing failed: {parse_error}")
                return self._default_classification(f"GigaChat classification error: {str(parse_error)}")
    
    def _get_tags_for_type(self, doc_type: str) -> list:
        """Get default tags for document type"""
        tag_map = {
            # Процессуальные документы
            "statement_of_claim": ["процессуальный", "исковое производство", "заявление"],
            "application": ["процессуальный", "заявление", "административный"],
            "response_to_claim": ["процессуальный", "отзыв", "ответ"],
            "counterclaim": ["процессуальный", "встречный иск"],
            "motion": ["процессуальный", "ходатайство"],
            "appeal": ["процессуальный", "жалоба", "апелляция"],
            "cassation": ["процессуальный", "жалоба", "кассация"],
            "supervisory_appeal": ["процессуальный", "жалоба", "надзор"],
            "protocol_remarks": ["процессуальный", "замечания"],
            "settlement_agreement": ["процессуальный", "мировое соглашение"],
            # Судебные акты
            "court_order": ["судебный акт", "приказ"],
            "court_decision": ["судебный акт", "решение"],
            "court_ruling": ["судебный акт", "определение"],
            "court_resolution": ["судебный акт", "постановление"],
            # Доказательства
            "contract": ["доказательство", "договор", "юридический"],
            "act": ["доказательство", "акт", "официальный"],
            "certificate": ["доказательство", "справка", "официальный"],
            "correspondence": ["доказательство", "переписка", "деловая"],
            "electronic_document": ["доказательство", "электронный"],
            "protocol": ["доказательство", "протокол", "официальный"],
            "expert_opinion": ["доказательство", "экспертиза", "заключение"],
            "specialist_consultation": ["доказательство", "консультация", "специалист"],
            "witness_statement": ["доказательство", "показания", "свидетель"],
            "audio_recording": ["доказательство", "аудио", "запись"],
            "video_recording": ["доказательство", "видео", "запись"],
            "physical_evidence": ["доказательство", "вещественное"],
            # Прочие
            "other": ["другое"]
        }
        return tag_map.get(doc_type, ["другое"])
    
    def _default_classification(self, reason: str) -> Dict[str, Any]:
        """Return default classification when error occurs"""
        return {
            "doc_type": "other",
            "tags": [],
            "confidence": 0.0,
            "needs_human_review": True,
            "reasoning": reason,
            "classifier": "default"
        }


