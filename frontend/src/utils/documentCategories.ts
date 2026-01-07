export const DOCUMENT_CATEGORIES = {
  court_acts: {
    label: "Судебные акты",
    docTypes: ["court_order", "court_decision", "court_ruling", "court_resolution"],
  },
  initiating: {
    label: "Инициирующие дело",
    docTypes: ["statement_of_claim", "order_application", "bankruptcy_application"],
  },
  response: {
    label: "Ответные документы",
    docTypes: ["response_to_claim", "counterclaim", "third_party_application", "third_party_objection"],
  },
  motions: {
    label: "Ходатайства",
    docTypes: [
      "motion",
      "motion_evidence",
      "motion_security",
      "motion_cancel_security",
      "motion_recusation",
      "motion_reinstatement",
    ],
  },
  appeals: {
    label: "Обжалование",
    docTypes: ["appeal", "cassation", "supervisory_appeal"],
  },
  special: {
    label: "Специальные производства",
    docTypes: [
      "arbitral_annulment",
      "arbitral_enforcement",
      "creditor_registry",
      "administrative_challenge",
      "admin_penalty_challenge",
    ],
  },
  settlement: {
    label: "Урегулирование",
    docTypes: ["settlement_agreement", "protocol_remarks"],
  },
  pre_trial: {
    label: "Досудебные документы",
    docTypes: ["pre_claim", "written_explanation"],
  },
  attachments: {
    label: "Приложения",
    docTypes: ["power_of_attorney", "egrul_extract", "state_duty"],
  },
  written_evidence: {
    label: "Письменные доказательства",
    docTypes: [
      "contract",
      "act",
      "certificate",
      "correspondence",
      "electronic_document",
      "protocol",
      "expert_opinion",
      "specialist_consultation",
      "witness_statement",
    ],
  },
  multimedia_evidence: {
    label: "Мультимедиа-доказательства",
    docTypes: ["audio_recording", "video_recording", "physical_evidence"],
  },
  other: {
    label: "Прочие",
    docTypes: ["other"],
  },
} as const

export type DocumentCategoryKey = keyof typeof DOCUMENT_CATEGORIES

export interface CategorizableDocument {
  id: string
  filename: string
  file_type?: string
  created_at?: string
  doc_type?: string | null
}

export function getCategoryForDocType(docType?: string | null): DocumentCategoryKey {
  if (!docType) return "other"
  
  const entry = (Object.entries(DOCUMENT_CATEGORIES) as [
    DocumentCategoryKey,
    (typeof DOCUMENT_CATEGORIES)[DocumentCategoryKey],
  ][]).find(([, cfg]) => cfg.docTypes.includes(docType))
  
  return entry ? entry[0] : "other"
}

export function groupDocumentsByCategory(
  documents: CategorizableDocument[],
): Record<DocumentCategoryKey, CategorizableDocument[]> {
  const result: Record<DocumentCategoryKey, CategorizableDocument[]> = {
    court_acts: [],
    initiating: [],
    response: [],
    motions: [],
    appeals: [],
    special: [],
    settlement: [],
    pre_trial: [],
    attachments: [],
    written_evidence: [],
    multimedia_evidence: [],
    other: [],
  }
  
  for (const doc of documents) {
    const cat = getCategoryForDocType(doc.doc_type)
    result[cat].push(doc)
  }
  
  return result
}



