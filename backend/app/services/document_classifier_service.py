"""Service for automatic document classification during upload"""
from typing import Dict, Any, Optional
from app.services.llm_factory import create_llm
from app.services.langchain_parsers import DocumentClassificationModel
from app.services.yandex_classifier import YandexDocumentClassifier
from app.config import config
from langchain_core.prompts import ChatPromptTemplate
import logging
import json
import os

logger = logging.getLogger(__name__)

# Порог уверенности для автоматической проверки
CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.75

# Полный набор типов документов арбитражных судов РФ (на основе АПК РФ)
DOCUMENT_TYPES = [
    # СУДЕБНЫЕ АКТЫ (ст. 15 АПК РФ)
    "court_order",             # Судебный приказ (гл. 29.1 АПК РФ) - упрощённое решение без разбирательства
    "court_decision",          # Решение (основной акт первой инстанции по существу)
    "court_ruling",            # Определение (акты по процессуальным вопросам)
    "court_resolution",        # Постановление (акты апелляционной и кассационной инстанций)
    
    # ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ УЧАСТНИКОВ - Инициирующие дело
    "statement_of_claim",      # Исковое заявление (ст. 125-126 АПК РФ)
    "order_application",       # Заявление о выдаче судебного приказа (гл. 29.1 АПК РФ)
    "bankruptcy_application",  # Заявление о признании должника банкротом (ФЗ № 127-ФЗ)
    
    # ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ УЧАСТНИКОВ - Ответные
    "response_to_claim",       # Отзыв на исковое заявление (ст. 131 АПК РФ)
    "counterclaim",            # Встречный иск (ст. 132 АПК РФ)
    "third_party_application", # Заявление о вступлении третьего лица в дело (ст. 50-51 АПК РФ)
    "third_party_objection",   # Возражения третьего лица (на мировое соглашение)
    
    # ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ УЧАСТНИКОВ - Ходатайства и заявления
    "motion",                  # Ходатайство (ст. 41, 159 АПК РФ) - общее
    "motion_evidence",         # Ходатайство о доказательствах (истребование, приобщение)
    "motion_security",         # Ходатайство об обеспечительных мерах
    "motion_cancel_security",  # Ходатайство об отмене обеспечения иска
    "motion_recusation",       # Ходатайство об отводе судьи
    "motion_reinstatement",    # Ходатайство о восстановлении пропущенного срока
    
    # ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ УЧАСТНИКОВ - Обжалование
    "appeal",                  # Апелляционная жалоба (1 месяц со дня оглашения)
    "cassation",               # Кассационная жалоба (ст. 291.1 АПК РФ, 2 месяца)
    "supervisory_appeal",      # Надзорная жалоба (ст. 308.2 АПК РФ, 3 месяца)
    
    # ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ УЧАСТНИКОВ - Специальные производства
    "arbitral_annulment",      # Заявление об отмене решения третейского суда (ст. 230-231 АПК РФ)
    "arbitral_enforcement",    # Заявление о выдаче исполнительного листа на решение третейского суда (ст. 237 АПК РФ)
    "creditor_registry",       # Заявление о включении требования в реестр требований кредиторов (ст. 71 ФЗ № 127-ФЗ)
    "administrative_challenge", # Заявление об оспаривании ненормативного правового акта (гл. 22 АПК РФ)
    "admin_penalty_challenge", # Заявление об оспаривании решения административного органа о привлечении к ответственности
    
    # ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ УЧАСТНИКОВ - Урегулирование
    "settlement_agreement",    # Мировое соглашение
    "protocol_remarks",        # Замечания на протокол судебного заседания
    
    # ДОСУДЕБНЫЕ ДОКУМЕНТЫ
    "pre_claim",               # Претензия (досудебное требование, 30 дней)
    "written_explanation",     # Письменное объяснение по делу
    
    # ПРИЛОЖЕНИЯ К ДОКУМЕНТАМ
    "power_of_attorney",       # Доверенность (подтверждение полномочий представителя)
    "egrul_extract",           # Выписка из ЕГРЮЛ/ЕГРИП (не ранее 30 дней до подачи)
    "state_duty",              # Документ об уплате государственной пошлины
    
    # ДОКАЗАТЕЛЬСТВА - Письменные
    "contract",                # Договор
    "act",                     # Акт (приема-передачи, выполненных работ и т.д.)
    "certificate",             # Справка
    "correspondence",          # Деловая переписка
    "electronic_document",     # Электронный документ
    "protocol",                # Протокол (совещаний, событий)
    "expert_opinion",          # Заключение эксперта
    "specialist_consultation", # Консультация специалиста
    "witness_statement",       # Показания свидетеля
    
    # ДОКАЗАТЕЛЬСТВА - Мультимедиа
    "audio_recording",         # Аудиозапись
    "video_recording",         # Видеозапись
    "physical_evidence",       # Вещественное доказательство
    
    # ПРОЧИЕ
    "other"                    # Другое (для документов, не подходящих под вышеперечисленные категории)
]


class DocumentClassifierService:
    """Service for classifying documents during upload"""
    
    def __init__(self):
        self.yandex_classifier = None
        self.llm = None
        self._init_classifiers()
    
    def _init_classifiers(self):
        """Initialize classifiers (Yandex preferred, GigaChat fallback)"""
        # #region debug log
        debug_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".cursor", "debug.log")
        try:
            os.makedirs(os.path.dirname(debug_log_path), exist_ok=True)
            with open(debug_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "B",
                    "location": "document_classifier_service.py:59",
                    "message": "Initializing classifiers",
                    "data": {
                        "has_yandex_key": bool(config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN),
                        "has_classifier_id": bool(config.YANDEX_AI_STUDIO_CLASSIFIER_ID)
                    },
                    "timestamp": int(__import__("time").time() * 1000)
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass  # Ignore debug log errors
        # #endregion
        
        # Пытаемся использовать Yandex AI Studio классификатор
        if (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN) and config.YANDEX_AI_STUDIO_CLASSIFIER_ID:
            try:
                self.yandex_classifier = YandexDocumentClassifier()
                if self.yandex_classifier.is_available():
                    # #region debug log
                    try:
                        with open(debug_log_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps({
                                "sessionId": "debug-session",
                                "runId": "run1",
                                "hypothesisId": "B",
                                "location": "document_classifier_service.py:68",
                                "message": "Yandex classifier available",
                                "data": {},
                                "timestamp": int(__import__("time").time() * 1000)
                            }, ensure_ascii=False) + "\n")
                    except Exception:
                        pass
                    # #endregion
                    logger.info("✅ Using Yandex AI Studio classifier for upload classification")
                    return
            except Exception as e:
                # #region debug log
                try:
                    with open(debug_log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "B",
                            "location": "document_classifier_service.py:75",
                            "message": "Yandex classifier init failed",
                            "data": {"error": str(e)},
                            "timestamp": int(__import__("time").time() * 1000)
                        }, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion
                logger.warning(f"Failed to initialize Yandex classifier: {e}, using GigaChat fallback")
        
        # Fallback to GigaChat LLM
        try:
            self.llm = create_llm(temperature=0.1)
            # #region debug log
            try:
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B",
                        "location": "document_classifier_service.py:85",
                        "message": "GigaChat LLM initialized",
                        "data": {},
                        "timestamp": int(__import__("time").time() * 1000)
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
            logger.info("✅ Using GigaChat LLM for document classification")
        except Exception as e:
            # #region debug log
            try:
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B",
                        "location": "document_classifier_service.py:92",
                        "message": "GigaChat LLM init failed",
                        "data": {"error": str(e)},
                        "timestamp": int(__import__("time").time() * 1000)
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
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
            # #region debug log
            import json
            import os
            debug_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".cursor", "debug.log")
            try:
                os.makedirs(os.path.dirname(debug_log_path), exist_ok=True)
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B",
                        "location": "document_classifier_service.py:103",
                        "message": "Choosing classifier",
                        "data": {
                            "has_yandex": bool(self.yandex_classifier),
                            "has_llm": bool(self.llm),
                            "text_length": len(prompt_text),
                            "filename": filename
                        },
                        "timestamp": int(__import__("time").time() * 1000)
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
            
            # Используем Yandex если доступен
            if self.yandex_classifier:
                return self._classify_with_yandex(prompt_text, filename)
            
            # Fallback to GigaChat
            if self.llm:
                return self._classify_with_llm(prompt_text, filename, case_context)
            
            # Если ни один классификатор не доступен, возвращаем дефолтную классификацию
            # #region debug log
            try:
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B",
                        "location": "document_classifier_service.py:120",
                        "message": "No classifier available",
                        "data": {},
                        "timestamp": int(__import__("time").time() * 1000)
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
            logger.warning("No classifier available, using default classification")
            return self._default_classification("No classifier available")
            
        except Exception as e:
            # #region debug log
            try:
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B",
                        "location": "document_classifier_service.py:127",
                        "message": "Classification exception",
                        "data": {"error": str(e), "error_type": type(e).__name__},
                        "timestamp": int(__import__("time").time() * 1000)
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
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
        system_prompt = f"""Ты эксперт по классификации документов арбитражных судов Российской Федерации.

Твоя задача: определить тип документа на основе Арбитражного процессуального кодекса РФ (АПК РФ).

Доступные типы документов (на основе полного справочника АПК РФ):

1. СУДЕБНЫЕ АКТЫ (ст. 15 АПК РФ):
   - court_order - Судебный приказ (гл. 29.1 АПК РФ) - упрощённое решение без судебного заседания, рассматривается 10 дней
   - court_decision - Решение - основной акт первой инстанции, разрешающий дело по существу (описательная, мотивировочная, резолютивная части)
   - court_ruling - Определение - акты по процессуальным вопросам (принятие иска, назначение экспертизы, приостановление дела)
   - court_resolution - Постановление - акты апелляционной и кассационной инстанций по результатам обжалования

2. ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ - Инициирующие дело:
   - statement_of_claim - Исковое заявление (ст. 125-126 АПК РФ) - основное обращение в спорах из гражданских правоотношений, содержит требования, обоснование, приложения
   - order_application - Заявление о выдаче судебного приказа (гл. 29.1 АПК РФ) - для упрощённого взыскания денежных требований
   - bankruptcy_application - Заявление о признании должника банкротом (ФЗ № 127-ФЗ) - может быть подано должником, кредитором или уполномоченным органом

3. ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ - Ответные:
   - response_to_claim - Отзыв на исковое заявление (ст. 131 АПК РФ) - обязательный документ ответчика с возражениями по каждому доводу иска
   - counterclaim - Встречный иск (ст. 132 АПК РФ) - иск ответчика к истцу, предъявляемый до завершения рассмотрения дела
   - third_party_application - Заявление о вступлении третьего лица в дело (ст. 50-51 АПК РФ) - с самостоятельными требованиями или без них
   - third_party_objection - Возражения третьего лица - на мировое соглашение или требование третьего лица

4. ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ - Ходатайства:
   - motion - Ходатайство (ст. 41, 159 АПК РФ) - общее ходатайство о процессуальных действиях
   - motion_evidence - Ходатайство о доказательствах - истребование, ознакомление, приобщение документов
   - motion_security - Ходатайство об обеспечительных мерах - принятие мер обеспечения иска
   - motion_cancel_security - Ходатайство об отмене обеспечения иска - после вступления решения в силу, рассматривается 5 дней
   - motion_recusation - Ходатайство об отводе судьи - отвод состава суда
   - motion_reinstatement - Ходатайство о восстановлении пропущенного срока - восстановление срока апелляции

5. ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ - Обжалование:
   - appeal - Апелляционная жалоба - подаётся в течение 1 месяца со дня оглашения решения, требует полного повторного рассмотрения
   - cassation - Кассационная жалоба (ст. 291.1 АПК РФ) - подаётся в течение 2 месяцев после вступления решения в силу, проверяет только соответствие нормам права
   - supervisory_appeal - Надзорная жалоба (ст. 308.2 АПК РФ) - подаётся в течение 3 месяцев в Верховный Суд РФ, требует существенного нарушения закона

6. ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ - Специальные производства:
   - arbitral_annulment - Заявление об отмене решения третейского суда (ст. 230-231 АПК РФ) - подаётся в течение 3 месяцев
   - arbitral_enforcement - Заявление о выдаче исполнительного листа на решение третейского суда (ст. 237 АПК РФ) - подаётся в течение 3 лет
   - creditor_registry - Заявление о включении требования в реестр требований кредиторов (ст. 71 ФЗ № 127-ФЗ) - в деле о банкротстве
   - administrative_challenge - Заявление об оспаривании ненормативного правового акта (гл. 22 АПК РФ) - индивидуальные акты госорганов
   - admin_penalty_challenge - Заявление об оспаривании решения административного органа о привлечении к ответственности - против постановлений об административных правонарушениях

7. ПРОЦЕССУАЛЬНЫЕ ДОКУМЕНТЫ - Урегулирование:
   - settlement_agreement - Мировое соглашение - соглашение сторон о прекращении судебного спора
   - protocol_remarks - Замечания на протокол судебного заседания - возражения на протокол

8. ДОСУДЕБНЫЕ ДОКУМЕНТЫ:
   - pre_claim - Претензия (досудебное требование) - направляется до подачи иска, срок 30 дней по умолчанию
   - written_explanation - Письменное объяснение по делу - позиция стороны по фактическим обстоятельствам

9. ПРИЛОЖЕНИЯ К ДОКУМЕНТАМ:
   - power_of_attorney - Доверенность - подтверждение полномочий представителя, должна быть нотариально заверена
   - egrul_extract - Выписка из ЕГРЮЛ/ЕГРИП - подтверждение регистрации, получается не ранее 30 дней до подачи
   - state_duty - Документ об уплате государственной пошлины - обязателен для любого документа, подаваемого в суд

10. ДОКАЗАТЕЛЬСТВА - Письменные:
   - contract - Договор - письменное соглашение между сторонами
   - act - Акт - документ, фиксирующий факт или событие (приема-передачи, выполненных работ)
   - certificate - Справка - документ, содержащий сведения о чем-либо
   - correspondence - Деловая переписка - письма, электронные сообщения, относящиеся к делу
   - electronic_document - Электронный документ - документ в электронном виде, имеющий юридическую силу
   - protocol - Протокол - документ, фиксирующий ход событий или совещаний
   - expert_opinion - Заключение эксперта - документ с выводами эксперта по поставленным вопросам
   - specialist_consultation - Консультация специалиста - письменная консультация по вопросам, требующим специальных знаний
   - witness_statement - Показания свидетеля - письменные или устные показания

11. ДОКАЗАТЕЛЬСТВА - Мультимедиа:
   - audio_recording - Аудиозапись - звукозапись, используемая в качестве доказательства
   - video_recording - Видеозапись - видеозапись, используемая в качестве доказательства
   - physical_evidence - Вещественное доказательство - физический объект, используемый в качестве доказательства

12. ПРОЧИЕ:
   - other - Другое - документ, не подходящий под вышеперечисленные категории

Верни структурированный ответ с полями:
- doc_type: один из доступных типов
- key_topics: массив тегов (например, ["процессуальный", "исковое производство"])
- confidence: уверенность от 0.0 до 1.0
- reasoning: подробное объяснение решения классификации с указанием признаков документа
- relevance_score: релевантность к делу (0-100)
- is_privileged: защищено ли привилегией (false)
- privilege_type: тип привилегии (none)

Будь точным и объективным. Обращай внимание на:
- Наличие реквизитов суда, участников, требований
- Ссылки на статьи АПК РФ
- Сроки подачи и рассмотрения
- Обязательные приложения
- Порядок обжалования

Если уверенность < {CLASSIFICATION_CONFIDENCE_THRESHOLD}, документ потребует ручной проверки."""

        user_prompt = f"""Классифицируй следующий документ:

Файл: {filename or 'Неизвестно'}

Текст документа:
{text[:15000]}

Определи тип документа, добавь релевантные теги и укажи уверенность классификации.

ВАЖНО: Верни ответ ТОЛЬКО в формате JSON с полями:
{{
  "doc_type": "один из доступных типов",
  "key_topics": ["тег1", "тег2"],
  "confidence": 0.85,
  "reasoning": "подробное объяснение",
  "relevance_score": 90,
  "is_privileged": false,
  "privilege_type": "none"
}}"""

        try:
            # #region debug log
            import json
            import os
            debug_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".cursor", "debug.log")
            try:
                os.makedirs(os.path.dirname(debug_log_path), exist_ok=True)
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "E",
                        "location": "document_classifier_service.py:216",
                        "message": "Starting LLM classification with structured output",
                        "data": {
                            "filename": filename,
                            "text_length": len(text),
                            "text_preview": text[:200]
                        },
                        "timestamp": int(__import__("time").time() * 1000)
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
            
            # Пытаемся использовать structured output
            try:
                structured_llm = self.llm.with_structured_output(DocumentClassificationModel)
                prompt = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("human", user_prompt)
                ])
                chain = prompt | structured_llm
                classification = chain.invoke({})
                
                # #region debug log
                try:
                    with open(debug_log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "E",
                            "location": "document_classifier_service.py:387",
                            "message": "LLM classification result received (structured)",
                            "data": {
                                "filename": filename,
                                "doc_type": getattr(classification, "doc_type", None),
                                "confidence": getattr(classification, "confidence", None),
                                "has_key_topics": bool(getattr(classification, "key_topics", None))
                            },
                            "timestamp": int(__import__("time").time() * 1000)
                        }, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion
                
                # Преобразуем в нужный формат
                confidence = float(classification.confidence) if isinstance(classification.confidence, (int, float)) else 0.5
                needs_human_review = confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD
                
                return {
                    "doc_type": classification.doc_type,
                    "tags": classification.key_topics or [],
                    "confidence": confidence,
                    "needs_human_review": needs_human_review,
                    "reasoning": classification.reasoning or "Классифицировано через GigaChat LLM (structured output)",
                    "classifier": "gigachat"
                }
            except Exception as structured_error:
                # Fallback: используем прямой вызов LLM без structured output
                logger.warning(f"Structured output failed: {structured_error}, using direct LLM call")
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt)
                ]
                response = self.llm.invoke(messages)
                # Правильно извлекаем content из ChatResult
                if hasattr(response, 'generations') and response.generations:
                    response_text = response.generations[0].message.content if hasattr(response.generations[0].message, 'content') else str(response.generations[0].message)
                elif hasattr(response, 'content'):
                    response_text = response.content
                else:
                    response_text = str(response)
                
                # #region debug log
                try:
                    with open(debug_log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "E",
                            "location": "document_classifier_service.py:417",
                            "message": "LLM response received (fallback)",
                            "data": {
                                "filename": filename,
                                "response_length": len(response_text),
                                "response_preview": response_text[:500]
                            },
                            "timestamp": int(__import__("time").time() * 1000)
                        }, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                # #endregion
                
                from app.services.langchain_parsers import ParserService
                classification = ParserService.parse_document_classification(response_text)
            
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
            # #region debug log
            try:
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "E",
                        "location": "document_classifier_service.py:258",
                        "message": "Classification failed",
                        "data": {
                            "filename": filename,
                            "error": str(e),
                            "error_type": type(e).__name__
                        },
                        "timestamp": int(__import__("time").time() * 1000)
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            # #endregion
            logger.warning(f"Classification failed: {e}, using default")
            return self._default_classification(f"GigaChat classification error: {str(e)}")
    
    def _get_tags_for_type(self, doc_type: str) -> list:
        """Get default tags for document type"""
        tag_map = {
            # СУДЕБНЫЕ АКТЫ
            "court_order": ["судебный акт", "приказ", "упрощенное производство"],
            "court_decision": ["судебный акт", "решение", "первая инстанция"],
            "court_ruling": ["судебный акт", "определение", "процессуальный вопрос"],
            "court_resolution": ["судебный акт", "постановление", "проверочная инстанция"],
            
            # ИНИЦИИРУЮЩИЕ ДОКУМЕНТЫ
            "statement_of_claim": ["процессуальный", "исковое производство", "заявление", "ст. 125-126 АПК"],
            "order_application": ["процессуальный", "заявление", "судебный приказ", "гл. 29.1 АПК"],
            "bankruptcy_application": ["процессуальный", "заявление", "банкротство", "ФЗ № 127-ФЗ"],
            
            # ОТВЕТНЫЕ ДОКУМЕНТЫ
            "response_to_claim": ["процессуальный", "отзыв", "ответ", "ст. 131 АПК"],
            "counterclaim": ["процессуальный", "встречный иск", "ст. 132 АПК"],
            "third_party_application": ["процессуальный", "третье лицо", "вступление в дело", "ст. 50-51 АПК"],
            "third_party_objection": ["процессуальный", "третье лицо", "возражения"],
            
            # ХОДАТАЙСТВА
            "motion": ["процессуальный", "ходатайство", "ст. 41, 159 АПК"],
            "motion_evidence": ["процессуальный", "ходатайство", "доказательства"],
            "motion_security": ["процессуальный", "ходатайство", "обеспечение иска"],
            "motion_cancel_security": ["процессуальный", "ходатайство", "отмена обеспечения"],
            "motion_recusation": ["процессуальный", "ходатайство", "отвод судьи"],
            "motion_reinstatement": ["процессуальный", "ходатайство", "восстановление срока"],
            
            # ОБЖАЛОВАНИЕ
            "appeal": ["процессуальный", "жалоба", "апелляция", "1 месяц"],
            "cassation": ["процессуальный", "жалоба", "кассация", "ст. 291.1 АПК", "2 месяца"],
            "supervisory_appeal": ["процессуальный", "жалоба", "надзор", "ст. 308.2 АПК", "3 месяца"],
            
            # СПЕЦИАЛЬНЫЕ ПРОИЗВОДСТВА
            "arbitral_annulment": ["процессуальный", "третейский суд", "отмена решения", "ст. 230-231 АПК"],
            "arbitral_enforcement": ["процессуальный", "третейский суд", "исполнительный лист", "ст. 237 АПК"],
            "creditor_registry": ["процессуальный", "банкротство", "реестр требований", "ст. 71 ФЗ № 127-ФЗ"],
            "administrative_challenge": ["процессуальный", "административный спор", "оспаривание акта", "гл. 22 АПК"],
            "admin_penalty_challenge": ["процессуальный", "административный спор", "оспаривание постановления"],
            
            # УРЕГУЛИРОВАНИЕ
            "settlement_agreement": ["процессуальный", "мировое соглашение", "урегулирование"],
            "protocol_remarks": ["процессуальный", "замечания", "протокол заседания"],
            
            # ДОСУДЕБНЫЕ
            "pre_claim": ["досудебный", "претензия", "30 дней"],
            "written_explanation": ["процессуальный", "объяснение", "позиция стороны"],
            
            # ПРИЛОЖЕНИЯ
            "power_of_attorney": ["приложение", "доверенность", "полномочия"],
            "egrul_extract": ["приложение", "выписка", "ЕГРЮЛ", "ЕГРИП"],
            "state_duty": ["приложение", "госпошлина", "квитанция"],
            
            # ДОКАЗАТЕЛЬСТВА - Письменные
            "contract": ["доказательство", "договор", "юридический"],
            "act": ["доказательство", "акт", "официальный"],
            "certificate": ["доказательство", "справка", "официальный"],
            "correspondence": ["доказательство", "переписка", "деловая"],
            "electronic_document": ["доказательство", "электронный"],
            "protocol": ["доказательство", "протокол", "официальный"],
            "expert_opinion": ["доказательство", "экспертиза", "заключение"],
            "specialist_consultation": ["доказательство", "консультация", "специалист"],
            "witness_statement": ["доказательство", "показания", "свидетель"],
            
            # ДОКАЗАТЕЛЬСТВА - Мультимедиа
            "audio_recording": ["доказательство", "аудио", "запись"],
            "video_recording": ["доказательство", "видео", "запись"],
            "physical_evidence": ["доказательство", "вещественное"],
            
            # ПРОЧИЕ
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


