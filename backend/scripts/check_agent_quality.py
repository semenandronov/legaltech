#!/usr/bin/env python3
"""
Скрипт для проверки качества работы агентов
Проверяет результаты анализа и оценивает качество работы каждого агента
"""
import sys
import os
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.utils.database import SessionLocal
from app.models.case import Case
from app.models.analysis import (
    AnalysisResult, TimelineEvent, Discrepancy,
    ExtractedEntity, DocumentClassification, PrivilegeCheck
)
from datetime import datetime
from typing import Dict, List, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_timeline_quality(case_id: str, db: Session) -> Dict[str, Any]:
    """Проверка качества работы Timeline агента"""
    events = db.query(TimelineEvent).filter(
        TimelineEvent.case_id == case_id
    ).all()
    
    if not events:
        return {
            "agent": "timeline",
            "status": "no_data",
            "quality_score": 0,
            "issues": ["Нет событий в хронологии"]
        }
    
    # Проверка качества
    issues = []
    quality_score = 100
    
    # Проверка наличия дат
    events_without_dates = [e for e in events if not e.date]
    if events_without_dates:
        issues.append(f"{len(events_without_dates)} событий без даты")
        quality_score -= 20
    
    # Проверка наличия описаний
    events_without_desc = [e for e in events if not e.description or len(e.description.strip()) < 10]
    if events_without_desc:
        issues.append(f"{len(events_without_desc)} событий с недостаточным описанием")
        quality_score -= 15
    
    # Проверка наличия источников
    events_without_source = [e for e in events if not e.source_document]
    if events_without_source:
        issues.append(f"{len(events_without_source)} событий без указания источника")
        quality_score -= 10
    
    # Проверка сортировки по датам
    sorted_events = sorted([e for e in events if e.date], key=lambda x: x.date)
    if len(sorted_events) != len([e for e in events if e.date]):
        issues.append("События не отсортированы по датам")
        quality_score -= 5
    
    quality_score = max(0, quality_score)
    
    return {
        "agent": "timeline",
        "status": "completed",
        "quality_score": quality_score,
        "total_events": len(events),
        "events_with_dates": len([e for e in events if e.date]),
        "events_with_sources": len([e for e in events if e.source_document]),
        "issues": issues,
        "sample_events": [
            {
                "date": e.date.isoformat() if e.date else None,
                "description": e.description[:100] if e.description else None,
                "source": e.source_document
            }
            for e in events[:3]
        ]
    }


def check_key_facts_quality(case_id: str, db: Session) -> Dict[str, Any]:
    """Проверка качества работы Key Facts агента"""
    result = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id,
        AnalysisResult.analysis_type == "key_facts"
    ).order_by(AnalysisResult.created_at.desc()).first()
    
    if not result or not result.result_data:
        return {
            "agent": "key_facts",
            "status": "no_data",
            "quality_score": 0,
            "issues": ["Нет данных о ключевых фактах"]
        }
    
    result_data = result.result_data if isinstance(result.result_data, dict) else {}
    facts = result_data.get("facts", []) if isinstance(result_data.get("facts"), list) else []
    
    if not facts:
        return {
            "agent": "key_facts",
            "status": "no_data",
            "quality_score": 0,
            "issues": ["Список фактов пуст"]
        }
    
    issues = []
    quality_score = 100
    
    # Проверка структуры фактов
    invalid_facts = [f for f in facts if not isinstance(f, dict) or not f.get("fact")]
    if invalid_facts:
        issues.append(f"{len(invalid_facts)} фактов с некорректной структурой")
        quality_score -= 25
    
    # Проверка наличия источников
    facts_without_source = [f for f in facts if isinstance(f, dict) and not f.get("source")]
    if facts_without_source:
        issues.append(f"{len(facts_without_source)} фактов без указания источника")
        quality_score -= 15
    
    # Проверка полноты описаний
    short_facts = [f for f in facts if isinstance(f, dict) and len(f.get("fact", "")) < 20]
    if short_facts:
        issues.append(f"{len(short_facts)} фактов с недостаточным описанием")
        quality_score -= 10
    
    quality_score = max(0, quality_score)
    
    return {
        "agent": "key_facts",
        "status": "completed",
        "quality_score": quality_score,
        "total_facts": len(facts),
        "facts_with_sources": len([f for f in facts if isinstance(f, dict) and f.get("source")]),
        "issues": issues,
        "sample_facts": facts[:3] if facts else []
    }


def check_discrepancies_quality(case_id: str, db: Session) -> Dict[str, Any]:
    """Проверка качества работы Discrepancy агента"""
    discrepancies = db.query(Discrepancy).filter(
        Discrepancy.case_id == case_id
    ).all()
    
    if not discrepancies:
        return {
            "agent": "discrepancy",
            "status": "no_data",
            "quality_score": 50,  # Отсутствие противоречий может быть нормальным
            "issues": ["Не найдено противоречий (это может быть нормально)"]
        }
    
    issues = []
    quality_score = 100
    
    # Проверка наличия описаний
    disc_without_desc = [d for d in discrepancies if not d.description or len(d.description.strip()) < 20]
    if disc_without_desc:
        issues.append(f"{len(disc_without_desc)} противоречий с недостаточным описанием")
        quality_score -= 20
    
    # Проверка наличия источников
    disc_without_source = [d for d in discrepancies if not d.source_documents]
    if disc_without_source:
        issues.append(f"{len(disc_without_source)} противоречий без указания источников")
        quality_score -= 15
    
    # Проверка наличия severity
    disc_without_severity = [d for d in discrepancies if not d.severity]
    if disc_without_severity:
        issues.append(f"{len(disc_without_severity)} противоречий без указания серьезности")
        quality_score -= 10
    
    quality_score = max(0, quality_score)
    
    return {
        "agent": "discrepancy",
        "status": "completed",
        "quality_score": quality_score,
        "total_discrepancies": len(discrepancies),
        "high_severity": len([d for d in discrepancies if d.severity == "HIGH"]),
        "medium_severity": len([d for d in discrepancies if d.severity == "MEDIUM"]),
        "low_severity": len([d for d in discrepancies if d.severity == "LOW"]),
        "issues": issues,
        "sample_discrepancies": [
            {
                "type": d.type,
                "severity": d.severity,
                "description": d.description[:100] if d.description else None
            }
            for d in discrepancies[:3]
        ]
    }


def check_risk_quality(case_id: str, db: Session) -> Dict[str, Any]:
    """Проверка качества работы Risk агента"""
    result = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id,
        AnalysisResult.analysis_type == "risk_analysis"
    ).order_by(AnalysisResult.created_at.desc()).first()
    
    if not result or not result.result_data:
        return {
            "agent": "risk",
            "status": "no_data",
            "quality_score": 0,
            "issues": ["Нет данных анализа рисков"]
        }
    
    result_data = result.result_data if isinstance(result.result_data, dict) else {}
    risks = result_data.get("risks", []) if isinstance(result_data.get("risks"), list) else []
    
    if not risks:
        return {
            "agent": "risk",
            "status": "no_data",
            "quality_score": 0,
            "issues": ["Список рисков пуст"]
        }
    
    issues = []
    quality_score = 100
    
    # Проверка структуры рисков
    invalid_risks = [r for r in risks if not isinstance(r, dict) or not r.get("risk_type")]
    if invalid_risks:
        issues.append(f"{len(invalid_risks)} рисков с некорректной структурой")
        quality_score -= 25
    
    # Проверка наличия оценок
    risks_without_score = [r for r in risks if isinstance(r, dict) and not r.get("risk_score")]
    if risks_without_score:
        issues.append(f"{len(risks_without_score)} рисков без оценки")
        quality_score -= 15
    
    # Проверка наличия рекомендаций
    risks_without_recommendation = [r for r in risks if isinstance(r, dict) and not r.get("recommendation")]
    if risks_without_recommendation:
        issues.append(f"{len(risks_without_recommendation)} рисков без рекомендаций")
        quality_score -= 10
    
    quality_score = max(0, quality_score)
    
    return {
        "agent": "risk",
        "status": "completed",
        "quality_score": quality_score,
        "total_risks": len(risks),
        "high_risks": len([r for r in risks if isinstance(r, dict) and r.get("risk_score", 0) >= 7]),
        "medium_risks": len([r for r in risks if isinstance(r, dict) and 4 <= r.get("risk_score", 0) < 7]),
        "low_risks": len([r for r in risks if isinstance(r, dict) and r.get("risk_score", 0) < 4]),
        "issues": issues,
        "sample_risks": risks[:3] if risks else []
    }


def check_summary_quality(case_id: str, db: Session) -> Dict[str, Any]:
    """Проверка качества работы Summary агента"""
    result = db.query(AnalysisResult).filter(
        AnalysisResult.case_id == case_id,
        AnalysisResult.analysis_type == "summary"
    ).order_by(AnalysisResult.created_at.desc()).first()
    
    if not result or not result.result_data:
        return {
            "agent": "summary",
            "status": "no_data",
            "quality_score": 0,
            "issues": ["Нет резюме"]
        }
    
    result_data = result.result_data if isinstance(result.result_data, dict) else {}
    summary_text = result_data.get("summary", "") if isinstance(result_data, dict) else ""
    
    if not summary_text or len(summary_text.strip()) < 50:
        return {
            "agent": "summary",
            "status": "no_data",
            "quality_score": 0,
            "issues": ["Резюме слишком короткое или отсутствует"]
        }
    
    issues = []
    quality_score = 100
    
    # Проверка длины резюме
    if len(summary_text) < 200:
        issues.append("Резюме слишком короткое (< 200 символов)")
        quality_score -= 20
    elif len(summary_text) > 5000:
        issues.append("Резюме слишком длинное (> 5000 символов)")
        quality_score -= 10
    
    # Проверка структуры (наличие абзацев)
    paragraphs = summary_text.split('\n\n')
    if len(paragraphs) < 2:
        issues.append("Резюме не структурировано (мало абзацев)")
        quality_score -= 10
    
    quality_score = max(0, quality_score)
    
    return {
        "agent": "summary",
        "status": "completed",
        "quality_score": quality_score,
        "summary_length": len(summary_text),
        "paragraphs_count": len(paragraphs),
        "issues": issues,
        "summary_preview": summary_text[:300] + "..." if len(summary_text) > 300 else summary_text
    }


def check_agent_quality(case_id: str) -> Dict[str, Any]:
    """Проверка качества работы всех агентов для дела"""
    db = SessionLocal()
    try:
        # Проверка существования дела
        case = db.query(Case).filter(Case.id == case_id).first()
        if not case:
            return {
                "error": f"Дело {case_id} не найдено"
            }
        
        # Проверка каждого агента
        results = {
            "case_id": case_id,
            "case_title": case.title,
            "checked_at": datetime.utcnow().isoformat(),
            "agents": {}
        }
        
        # Timeline agent
        results["agents"]["timeline"] = check_timeline_quality(case_id, db)
        
        # Key Facts agent
        results["agents"]["key_facts"] = check_key_facts_quality(case_id, db)
        
        # Discrepancy agent
        results["agents"]["discrepancy"] = check_discrepancies_quality(case_id, db)
        
        # Risk agent
        results["agents"]["risk"] = check_risk_quality(case_id, db)
        
        # Summary agent
        results["agents"]["summary"] = check_summary_quality(case_id, db)
        
        # Общая оценка
        quality_scores = [agent["quality_score"] for agent in results["agents"].values() if agent.get("quality_score") is not None]
        if quality_scores:
            results["overall_quality_score"] = sum(quality_scores) / len(quality_scores)
            results["overall_status"] = "excellent" if results["overall_quality_score"] >= 90 else \
                                       "good" if results["overall_quality_score"] >= 70 else \
                                       "fair" if results["overall_quality_score"] >= 50 else "poor"
        else:
            results["overall_quality_score"] = 0
            results["overall_status"] = "no_data"
        
        return results
        
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_agent_quality.py <case_id>")
        sys.exit(1)
    
    case_id = sys.argv[1]
    results = check_agent_quality(case_id)
    
    print(json.dumps(results, indent=2, ensure_ascii=False))

















































