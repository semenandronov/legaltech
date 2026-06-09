"""Canonical Russian labels for document classification doc_type codes."""

from typing import Dict

# Shared with RAG metadata and document classification.
DOC_TYPE_LABELS: Dict[str, str] = {
    "court_order": "Судебный приказ",
    "court_decision": "Решение",
    "court_ruling": "Определение",
    "court_resolution": "Постановление",
    "statement_of_claim": "Исковое заявление",
    "order_application": "Заявление о выдаче судебного приказа",
    "bankruptcy_application": "Заявление о признании должника банкротом",
    "response_to_claim": "Отзыв на исковое заявление",
    "counterclaim": "Встречный иск",
    "third_party_application": "Заявление о вступлении третьего лица в дело",
    "third_party_objection": "Возражения третьего лица",
    "motion": "Ходатайство",
    "motion_evidence": "Ходатайство о доказательствах",
    "motion_security": "Ходатайство об обеспечительных мерах",
    "motion_cancel_security": "Ходатайство об отмене обеспечения иска",
    "motion_recusation": "Ходатайство об отводе судьи",
    "motion_reinstatement": "Ходатайство о восстановлении пропущенного срока",
    "appeal": "Апелляционная жалоба",
    "cassation": "Кассационная жалоба",
    "supervisory_appeal": "Надзорная жалоба",
    "arbitral_annulment": "Заявление об отмене решения третейского суда",
    "arbitral_enforcement": "Заявление о выдаче исполнительного листа на решение третейского суда",
    "creditor_registry": "Заявление о включении требования в реестр требований кредиторов",
    "administrative_challenge": "Заявление об оспаривании ненормативного правового акта",
    "admin_penalty_challenge": "Заявление об оспаривании решения административного органа",
    "settlement_agreement": "Мировое соглашение",
    "protocol_remarks": "Замечания на протокол судебного заседания",
    "pre_claim": "Претензия (досудебное требование)",
    "written_explanation": "Письменное объяснение по делу",
    "power_of_attorney": "Доверенность",
    "egrul_extract": "Выписка из ЕГРЮЛ/ЕГРИП",
    "state_duty": "Документ об уплате государственной пошлины",
    "contract": "Договор",
    "act": "Акт",
    "certificate": "Справка",
    "correspondence": "Деловая переписка",
    "electronic_document": "Электронный документ",
    "protocol": "Протокол",
    "expert_opinion": "Заключение эксперта",
    "specialist_consultation": "Консультация специалиста",
    "witness_statement": "Показания свидетеля",
    "audio_recording": "Аудиозапись",
    "video_recording": "Видеозапись",
    "physical_evidence": "Вещественное доказательство",
    "other": "Другое",
}


def doc_type_display_label(doc_type: str) -> str:
    """Human-readable Russian label for a classification code."""
    key = (doc_type or "").strip()
    if not key:
        return "Другое"
    return DOC_TYPE_LABELS.get(key, key.replace("_", " ").capitalize())
