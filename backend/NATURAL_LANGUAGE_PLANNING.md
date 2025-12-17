# Планирование задач на естественном языке для агентов

## Текущее состояние

### ❌ Что НЕ работает сейчас:

**Задача на естественном языке не поддерживается**

Сейчас для запуска анализов нужно **явно указать типы анализов** в массиве:

```python
# Текущий API (analysis.py)
POST /api/analysis/{case_id}/start
{
    "analysis_types": ["timeline", "key_facts", "discrepancy", "risk", "summary"]
}
```

**Чат работает только для вопросов по документам:**
- Задать вопрос → получить ответ на основе документов (RAG)
- НЕ запускает анализы
- НЕ планирует задачи

### ✅ Что работает сейчас:

1. **Чат с RAG** (`/api/chat`)
   - Вопросы по документам
   - Ответы с источниками
   - История чата

2. **Запуск анализов** (`/api/analysis/{case_id}/start`)
   - Явное указание типов анализов
   - Мультиагентная система (если `AGENT_ENABLED=true`)
   - Фоновое выполнение

---

## Как это должно работать (как у Legora/Harvey AI)

### Пример использования:

```
Пользователь в чате: "Проанализируй документы и найди все риски и противоречия"

Система должна:
1. Понять задачу (NLP)
2. Определить необходимые анализы:
   - discrepancy (для противоречий)
   - risk (для рисков, но требует discrepancy)
3. Создать план выполнения
4. Запустить агентов
5. Вернуть результаты
```

---

## Реализация: Planning Agent

### Архитектура решения

```
┌─────────────────────────────────────────┐
│   User Input (Natural Language)         │
│   "Найди все риски в документах"        │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│   Planning Agent                        │
│   - Анализ задачи на естественном языке │
│   - Определение необходимых анализов    │
│   - Создание плана выполнения           │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│   Analysis Plan                         │
│   analysis_types: ["discrepancy",       │
│                    "risk"]              │
│   reasoning: "Risk требует discrepancy" │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│   Agent Coordinator                     │
│   - Запуск мультиагентной системы       │
│   - Выполнение плана                    │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│   Results + Explanation                 │
│   "Выполнен анализ рисков на основе     │
│    найденных противоречий..."           │
└─────────────────────────────────────────┘
```

---

## Код реализации

### 1. Planning Agent (новый файл)

**Файл:** `backend/app/services/langchain_agents/planning_agent.py`

```python
"""Planning agent for natural language task understanding"""
from typing import List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.config import config
import json
import logging

logger = logging.getLogger(__name__)


class PlanningAgent:
    """Agent that converts natural language tasks to analysis plans"""
    
    # Доступные типы анализов и их описания
    AVAILABLE_ANALYSES = {
        "timeline": {
            "name": "timeline",
            "description": "Извлечение хронологии событий из документов",
            "keywords": ["даты", "события", "хронология", "timeline", "timeline событий"],
            "dependencies": []
        },
        "key_facts": {
            "name": "key_facts",
            "description": "Извлечение ключевых фактов из документов",
            "keywords": ["факты", "ключевые факты", "key facts", "основные моменты"],
            "dependencies": []
        },
        "discrepancy": {
            "name": "discrepancy",
            "description": "Поиск противоречий и несоответствий в документах",
            "keywords": ["противоречия", "несоответствия", "discrepancy", "расхождения", "конфликты"],
            "dependencies": []
        },
        "risk": {
            "name": "risk",
            "description": "Анализ рисков на основе найденных противоречий",
            "keywords": ["риски", "risk", "анализ рисков", "оценка рисков", "риск-анализ"],
            "dependencies": ["discrepancy"]  # Требует discrepancy
        },
        "summary": {
            "name": "summary",
            "description": "Генерация резюме дела на основе ключевых фактов",
            "keywords": ["резюме", "summary", "краткое содержание", "сводка"],
            "dependencies": ["key_facts"]  # Требует key_facts
        }
    }
    
    def __init__(self):
        """Initialize planning agent"""
        self.llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.1,  # Низкая температура для консистентности
            max_tokens=500
        )
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты - планировщик задач для юридической AI-системы. 
Твоя задача - понять, что хочет пользователь, и определить, какие анализы нужно выполнить.

Доступные типы анализов:
1. timeline - извлечение хронологии событий (даты, события)
2. key_facts - извлечение ключевых фактов
3. discrepancy - поиск противоречий и несоответствий
4. risk - анализ рисков (требует discrepancy)
5. summary - генерация резюме (требует key_facts)

Верни JSON со следующим форматом:
{{
    "analysis_types": ["timeline", "key_facts", ...],
    "reasoning": "Объяснение почему выбраны эти анализы",
    "confidence": 0.9
}}

Если задача неясна, включи наиболее вероятные анализы и укажи это в reasoning."""),
            ("human", "Задача пользователя: {user_task}\n\nДокументы загружены для дела {case_id}. Определи, какие анализы нужно выполнить.")
        ])
    
    def plan_analysis(
        self, 
        user_task: str, 
        case_id: str,
        available_documents: List[str] = None
    ) -> Dict[str, Any]:
        """
        Создает план анализа на основе задачи пользователя
        
        Args:
            user_task: Задача пользователя на естественном языке
            case_id: Идентификатор дела
            available_documents: Список доступных документов (опционально)
        
        Returns:
            Dictionary с планом анализа:
            {
                "analysis_types": ["timeline", "key_facts"],
                "reasoning": "Выбраны эти анализы потому что...",
                "confidence": 0.9
            }
        """
        try:
            logger.info(f"Planning analysis for task: {user_task[:100]}...")
            
            # Формируем промпт
            messages = self.prompt.format_messages(
                user_task=user_task,
                case_id=case_id
            )
            
            # Получаем ответ от LLM
            response = self.llm.invoke(messages)
            response_text = response.content.strip()
            
            # Парсим JSON ответ
            # Убираем markdown code blocks если есть
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            plan = json.loads(response_text)
            
            # Валидация и добавление зависимостей
            validated_types = self._validate_and_add_dependencies(plan.get("analysis_types", []))
            plan["analysis_types"] = validated_types
            
            logger.info(
                f"Analysis plan created: {validated_types}, "
                f"confidence: {plan.get('confidence', 0.8)}"
            )
            
            return plan
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse planning response: {e}, response: {response_text}")
            # Fallback: простая эвристика
            return self._fallback_planning(user_task)
        except Exception as e:
            logger.error(f"Error in planning agent: {e}", exc_info=True)
            return self._fallback_planning(user_task)
    
    def _validate_and_add_dependencies(self, analysis_types: List[str]) -> List[str]:
        """
        Валидирует типы анализов и добавляет зависимости
        
        Args:
            analysis_types: Список типов анализов
        
        Returns:
            Валидированный список с зависимостями
        """
        validated = []
        seen = set()
        
        # Функция для добавления с зависимостями
        def add_with_dependencies(analysis_type: str):
            if analysis_type in seen:
                return
            
            analysis_info = self.AVAILABLE_ANALYSES.get(analysis_type)
            if not analysis_info:
                logger.warning(f"Unknown analysis type: {analysis_type}")
                return
            
            # Добавляем зависимости сначала
            for dep in analysis_info["dependencies"]:
                add_with_dependencies(dep)
            
            # Добавляем сам анализ
            validated.append(analysis_type)
            seen.add(analysis_type)
        
        # Добавляем все анализы с зависимостями
        for analysis_type in analysis_types:
            add_with_dependencies(analysis_type)
        
        return validated
    
    def _fallback_planning(self, user_task: str) -> Dict[str, Any]:
        """
        Простое планирование на основе ключевых слов (fallback)
        
        Args:
            user_task: Задача пользователя
        
        Returns:
            План анализа
        """
        user_task_lower = user_task.lower()
        selected = []
        
        # Простая эвристика на основе ключевых слов
        for analysis_type, info in self.AVAILABLE_ANALYSES.items():
            for keyword in info["keywords"]:
                if keyword.lower() in user_task_lower:
                    selected.append(analysis_type)
                    break
        
        # Если ничего не найдено, возвращаем все основные анализы
        if not selected:
            selected = ["timeline", "key_facts", "discrepancy"]
        
        # Добавляем зависимости
        validated = self._validate_and_add_dependencies(selected)
        
        return {
            "analysis_types": validated,
            "reasoning": f"Fallback планирование на основе ключевых слов: {user_task}",
            "confidence": 0.6
        }
```

### 2. Интеграция в Chat endpoint

**Обновление:** `backend/app/routes/chat.py`

Добавить новый endpoint для планирования и выполнения задач:

```python
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.analysis_service import AnalysisService
from fastapi import BackgroundTasks

class TaskRequest(BaseModel):
    """Request model for natural language task"""
    case_id: str = Field(..., min_length=1)
    task: str = Field(..., min_length=1, max_length=5000, description="Task in natural language")

class TaskResponse(BaseModel):
    """Response model for task execution"""
    plan: Dict[str, Any]  # Analysis plan
    status: str  # "planned", "executing", "completed"
    message: str

@router.post("/task", response_model=TaskResponse)
async def execute_task(
    request: TaskRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Execute task in natural language using planning agent
    
    Example: "Проанализируй документы и найди все риски"
    """
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == request.case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Create planning agent
    planning_agent = PlanningAgent()
    
    # Plan analysis
    plan = planning_agent.plan_analysis(
        user_task=request.task,
        case_id=request.case_id
    )
    
    analysis_types = plan["analysis_types"]
    reasoning = plan.get("reasoning", "")
    
    # Start analysis in background
    def run_planned_analysis():
        from app.utils.database import SessionLocal
        background_db = SessionLocal()
        try:
            analysis_service = AnalysisService(background_db)
            if analysis_service.use_agents:
                results = analysis_service.run_agent_analysis(
                    request.case_id, 
                    analysis_types
                )
                logger.info(f"Task execution completed for case {request.case_id}")
            else:
                # Legacy approach
                for analysis_type in analysis_types:
                    # Map to legacy methods
                    pass
        finally:
            background_db.close()
    
    background_tasks.add_task(run_planned_analysis)
    
    return TaskResponse(
        plan={
            "analysis_types": analysis_types,
            "reasoning": reasoning,
            "confidence": plan.get("confidence", 0.8)
        },
        status="executing",
        message=f"Задача запланирована: {reasoning}"
    )
```

### 3. Обновление Chat endpoint для поддержки задач

**Обновление:** `backend/app/routes/chat.py`

Добавить обработку задач в основном chat endpoint:

```python
import re

def is_task_request(question: str) -> bool:
    """
    Определяет, является ли запрос задачей для выполнения анализов
    или обычным вопросом
    """
    task_keywords = [
        "проанализируй", "выполни", "найди", "извлеки", 
        "создай", "сделай", "запусти", "проведи анализ",
        "analyze", "extract", "find", "create", "generate"
    ]
    
    question_lower = question.lower()
    
    # Проверка на команды выполнения
    for keyword in task_keywords:
        if keyword in question_lower:
            return True
    
    # Проверка на конкретные типы анализов
    analysis_keywords = [
        "timeline", "хронология", "даты",
        "key facts", "ключевые факты",
        "discrepancy", "противоречия",
        "risk", "риски",
        "summary", "резюме"
    ]
    
    for keyword in analysis_keywords:
        if keyword in question_lower:
            return True
    
    return False

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,  # Добавлено
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Send question to ChatGPT based on case documents OR execute task"""
    
    # Проверяем, является ли это задачей
    if is_task_request(request.question):
        # Это задача - используем planning agent
        planning_agent = PlanningAgent()
        plan = planning_agent.plan_analysis(
            user_task=request.question,
            case_id=request.case_id
        )
        
        # Запускаем анализ в фоне
        # ... (код запуска анализа)
        
        # Возвращаем ответ о планировании
        answer = f"""Я понял вашу задачу и запланировал следующие анализы:

{', '.join(plan['analysis_types'])}

**Объяснение:** {plan.get('reasoning', '')}

Анализ выполняется в фоне. Результаты будут доступны через несколько минут."""
        
        return ChatResponse(
            answer=answer,
            sources=[],
            status="task_planned"
        )
    
    # Обычный вопрос - используем RAG
    # ... (существующий код)
```

---

## Примеры использования

### Пример 1: Простая задача
```
Пользователь: "Найди все противоречия в документах"

Planning Agent определяет:
- analysis_types: ["discrepancy"]
- reasoning: "Пользователь просит найти противоречия, нужен анализ discrepancy"
```

### Пример 2: Сложная задача с зависимостями
```
Пользователь: "Проанализируй риски"

Planning Agent определяет:
- analysis_types: ["discrepancy", "risk"]
- reasoning: "Анализ рисков требует наличия противоречий, поэтому сначала выполняется discrepancy, затем risk"
```

### Пример 3: Комплексная задача
```
Пользователь: "Сделай полный анализ: извлеки ключевые факты, найди противоречия и создай резюме"

Planning Agent определяет:
- analysis_types: ["key_facts", "discrepancy", "summary"]
- reasoning: "Пользователь запросил комплексный анализ. Summary требует key_facts"
```

---

## Преимущества реализации

1. **Естественный интерфейс** - как у Legora и Harvey AI
2. **Автономное планирование** - система сама определяет, что нужно
3. **Учет зависимостей** - автоматическое добавление необходимых анализов
4. **Интеграция с чатом** - один интерфейс для вопросов и задач
5. **Объяснимость** - система объясняет, почему выбраны те или иные анализы

---

## Следующие шаги

1. ✅ Создать `planning_agent.py`
2. ✅ Добавить endpoint `/api/chat/task`
3. ✅ Обновить `/api/chat/` для обработки задач
4. ⏳ Тестирование планирования
5. ⏳ Улучшение промптов для planning agent
6. ⏳ Добавление confidence scoring
7. ⏳ Обработка неоднозначных задач

---

*Документ создан: 2024-12-16*
