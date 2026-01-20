#!/usr/bin/env python3
"""
Проверка качества работы агентов через API
Анализирует результаты работы каждого агента и выдает оценку качества
"""
import requests
import json
import sys
from typing import Dict, Any, List

BASE_URL = "https://legaltech-iq1b.onrender.com"


def check_timeline_quality(case_id: str, token: str) -> Dict[str, Any]:
    """Проверка качества Timeline агента"""
    try:
        response = requests.get(
            f"{BASE_URL}/api/analysis/{case_id}/timeline",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code != 200:
            return {
                "agent": "timeline",
                "status": "error",
                "quality_score": 0,
                "error": f"HTTP {response.status_code}: {response.text[:100]}"
            }
        
        data = response.json()
        events = data.get("events", [])
        
        if not events:
            return {
                "agent": "timeline",
                "status": "no_data",
                "quality_score": 0,
                "issues": ["Нет событий в хронологии"]
            }
        
        issues = []
        quality_score = 100
        
        # Проверка наличия дат
        events_without_dates = [e for e in events if not e.get("date")]
        if events_without_dates:
            issues.append(f"{len(events_without_dates)} событий без даты")
            quality_score -= 20
        
        # Проверка наличия описаний
        events_without_desc = [e for e in events if not e.get("description") or len(e.get("description", "")) < 10]
        if events_without_desc:
            issues.append(f"{len(events_without_desc)} событий с недостаточным описанием")
            quality_score -= 15
        
        # Проверка наличия источников
        events_without_source = [e for e in events if not e.get("source_document")]
        if events_without_source:
            issues.append(f"{len(events_without_source)} событий без указания источника")
            quality_score -= 10
        
        quality_score = max(0, quality_score)
        
        return {
            "agent": "timeline",
            "status": "completed",
            "quality_score": quality_score,
            "total_events": len(events),
            "events_with_dates": len([e for e in events if e.get("date")]),
            "events_with_sources": len([e for e in events if e.get("source_document")]),
            "issues": issues,
            "sample_events": events[:2]
        }
    except Exception as e:
        return {
            "agent": "timeline",
            "status": "error",
            "quality_score": 0,
            "error": str(e)
        }


def check_key_facts_quality(case_id: str, token: str) -> Dict[str, Any]:
    """Проверка качества Key Facts агента"""
    try:
        response = requests.get(
            f"{BASE_URL}/api/analysis/{case_id}/key-facts",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code != 200:
            return {
                "agent": "key_facts",
                "status": "error",
                "quality_score": 0,
                "error": f"HTTP {response.status_code}: {response.text[:100]}"
            }
        
        data = response.json()
        facts = data.get("facts", {})
        
        if not facts or (isinstance(facts, dict) and not facts):
            return {
                "agent": "key_facts",
                "status": "no_data",
                "quality_score": 0,
                "issues": ["Нет данных о ключевых фактах"]
            }
        
        # Если facts - это словарь, преобразуем в список
        if isinstance(facts, dict):
            facts_list = [{"fact": k, "value": v} for k, v in facts.items()]
        elif isinstance(facts, list):
            facts_list = facts
        else:
            facts_list = []
        
        if not facts_list:
            return {
                "agent": "key_facts",
                "status": "no_data",
                "quality_score": 0,
                "issues": ["Список фактов пуст"]
            }
        
        issues = []
        quality_score = 100
        
        # Проверка структуры фактов
        invalid_facts = [f for f in facts_list if not isinstance(f, dict) or not f.get("fact")]
        if invalid_facts:
            issues.append(f"{len(invalid_facts)} фактов с некорректной структурой")
            quality_score -= 25
        
        # Проверка полноты описаний
        short_facts = [f for f in facts_list if isinstance(f, dict) and len(str(f.get("fact", ""))) < 10]
        if short_facts:
            issues.append(f"{len(short_facts)} фактов с недостаточным описанием")
            quality_score -= 10
        
        quality_score = max(0, quality_score)
        
        return {
            "agent": "key_facts",
            "status": "completed",
            "quality_score": quality_score,
            "total_facts": len(facts_list),
            "issues": issues,
            "sample_facts": facts_list[:2] if facts_list else []
        }
    except Exception as e:
        return {
            "agent": "key_facts",
            "status": "error",
            "quality_score": 0,
            "error": str(e)
        }


def check_discrepancies_quality(case_id: str, token: str) -> Dict[str, Any]:
    """Проверка качества Discrepancy агента"""
    try:
        response = requests.get(
            f"{BASE_URL}/api/analysis/{case_id}/discrepancies",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code != 200:
            return {
                "agent": "discrepancy",
                "status": "error",
                "quality_score": 0,
                "error": f"HTTP {response.status_code}: {response.text[:100]}"
            }
        
        data = response.json()
        discrepancies = data.get("discrepancies", [])
        
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
        disc_without_desc = [d for d in discrepancies if not d.get("description") or len(d.get("description", "")) < 20]
        if disc_without_desc:
            issues.append(f"{len(disc_without_desc)} противоречий с недостаточным описанием")
            quality_score -= 20
        
        # Проверка наличия источников
        disc_without_source = [d for d in discrepancies if not d.get("source_documents")]
        if disc_without_source:
            issues.append(f"{len(disc_without_source)} противоречий без указания источников")
            quality_score -= 15
        
        # Проверка наличия severity
        disc_without_severity = [d for d in discrepancies if not d.get("severity")]
        if disc_without_severity:
            issues.append(f"{len(disc_without_severity)} противоречий без указания серьезности")
            quality_score -= 10
        
        quality_score = max(0, quality_score)
        
        return {
            "agent": "discrepancy",
            "status": "completed",
            "quality_score": quality_score,
            "total_discrepancies": len(discrepancies),
            "high_severity": data.get("high_risk", 0),
            "medium_severity": data.get("medium_risk", 0),
            "low_severity": data.get("low_risk", 0),
            "issues": issues,
            "sample_discrepancies": discrepancies[:2] if discrepancies else []
        }
    except Exception as e:
        return {
            "agent": "discrepancy",
            "status": "error",
            "quality_score": 0,
            "error": str(e)
        }


def check_risk_quality(case_id: str, token: str) -> Dict[str, Any]:
    """Проверка качества Risk агента"""
    try:
        response = requests.get(
            f"{BASE_URL}/api/analysis/{case_id}/risks",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code != 200:
            return {
                "agent": "risk",
                "status": "error",
                "quality_score": 0,
                "error": f"HTTP {response.status_code}: {response.text[:100]}"
            }
        
        data = response.json()
        risks = data.get("risks", [])
        
        if not risks:
            return {
                "agent": "risk",
                "status": "no_data",
                "quality_score": 0,
                "issues": ["Нет данных анализа рисков"]
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
            "sample_risks": risks[:2] if risks else []
        }
    except Exception as e:
        return {
            "agent": "risk",
            "status": "error",
            "quality_score": 0,
            "error": str(e)
        }


def check_summary_quality(case_id: str, token: str) -> Dict[str, Any]:
    """Проверка качества Summary агента"""
    try:
        response = requests.get(
            f"{BASE_URL}/api/analysis/{case_id}/summary",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if response.status_code != 200:
            return {
                "agent": "summary",
                "status": "error",
                "quality_score": 0,
                "error": f"HTTP {response.status_code}: {response.text[:100]}"
            }
        
        data = response.json()
        summary_text = data.get("summary", "")
        
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
    except Exception as e:
        return {
            "agent": "summary",
            "status": "error",
            "quality_score": 0,
            "error": str(e)
        }


def check_all_agents(case_id: str, token: str) -> Dict[str, Any]:
    """Проверка качества всех агентов"""
    results = {
        "case_id": case_id,
        "checked_at": None,
        "agents": {}
    }
    
    # Проверка каждого агента
    results["agents"]["timeline"] = check_timeline_quality(case_id, token)
    results["agents"]["key_facts"] = check_key_facts_quality(case_id, token)
    results["agents"]["discrepancy"] = check_discrepancies_quality(case_id, token)
    results["agents"]["risk"] = check_risk_quality(case_id, token)
    results["agents"]["summary"] = check_summary_quality(case_id, token)
    
    # Общая оценка
    quality_scores = [
        agent["quality_score"] 
        for agent in results["agents"].values() 
        if agent.get("quality_score") is not None and agent.get("status") != "error"
    ]
    
    if quality_scores:
        results["overall_quality_score"] = sum(quality_scores) / len(quality_scores)
        results["overall_status"] = (
            "excellent" if results["overall_quality_score"] >= 90 else
            "good" if results["overall_quality_score"] >= 70 else
            "fair" if results["overall_quality_score"] >= 50 else "poor"
        )
    else:
        results["overall_quality_score"] = 0
        results["overall_status"] = "no_data"
    
    from datetime import datetime
    results["checked_at"] = datetime.utcnow().isoformat()
    
    return results


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python check_agents_api.py <case_id> <access_token>")
        print("\nДля получения токена:")
        print("1. Войдите в систему через браузер")
        print("2. Откройте DevTools (F12)")
        print("3. Перейдите в Application/Storage > Local Storage")
        print("4. Скопируйте значение 'access_token'")
        sys.exit(1)
    
    case_id = sys.argv[1]
    token = sys.argv[2]
    
    results = check_all_agents(case_id, token)
    print(json.dumps(results, indent=2, ensure_ascii=False))






























































