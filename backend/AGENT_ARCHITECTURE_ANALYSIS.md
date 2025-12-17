# Анализ архитектуры агентных систем: Legora и Harvey AI

## Введение

Этот документ содержит анализ архитектуры агентных систем двух ведущих ИИ-стартапов в юридической области: **Legora** (ранее Leya) и **Harvey AI**. Анализ выполнен для понимания лучших практик и получения рекомендаций по улучшению нашей мультиагентной системы.

---

## 1. Legora (ранее Leya)

### 1.1. Архитектура

**Agentic Workflows** — ключевая особенность Legora, которая позволяет:
- Вводить высокоуровневые цели на естественном языке
- Автономно планировать и выполнять задачи
- Интегрировать различные инструменты и источники данных

### 1.2. Ключевые компоненты

#### **Workflows Framework**
- **Входные данные**: естественный язык + документы
- **Процесс**: 
  1. Планирование задачи
  2. Извлечение критической информации
  3. Выявление потенциальных рисков
  4. Создание разделов финального отчета
- **Пример использования**: Due diligence — загрузка документов → анализ → извлечение информации → выделение рисков → черновик отчета

#### **Интеграции**
- **Microsoft Word add-in**: взаимодействие с AI непосредственно в документах
- **Real-time collaboration**: одновременная работа нескольких пользователей
- **Интеграция с существующими юридическими инструментами**

#### **Адаптация под фирмы**
- Тесное сотрудничество с юридическими фирмами
- Кастомизация под специфические workflows и протоколы фирм
- Обеспечение консистентности и качества

### 1.3. Технические особенности

```
┌─────────────────────────────────────────┐
│      Natural Language Input              │
│   (High-level goals + Documents)         │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│      Agentic Planning Layer              │
│   (Autonomous task planning)             │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│      Execution Layer                     │
│   - Document analysis                    │
│   - Information extraction               │
│   - Risk identification                  │
│   - Report generation                    │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│      Integration Layer                   │
│   - Legal databases                      │
│   - Web search (case law)                │
│   - Citation verification                │
└─────────────────────────────────────────┘
```

---

## 2. Harvey AI

### 2.1. Архитектура Multi-Agent System

Harvey использует **сложную мультиагентную архитектуру** с специализированными агентами.

#### **Специализированные агенты**
- **Antitrust filing analysis**
- **Cybersecurity**
- **Fund formation**
- **Loan review**
- И другие домен-специфичные агенты

### 2.2. Ключевые компоненты

#### **Collaborative Planning and Execution**
- **Планирование многоэтапных задач**: агенты могут предсказывать и планировать сложные задачи
- **Выявление неоднозначностей**: агенты идентифицируют неясности и запрашивают дополнительную информацию
- **Адаптация стратегии**: изменение подхода на основе обратной связи

#### **Модели и оптимизация**
- **Модели**: OpenAI o1, GPT-5, Anthropic, Google
- **Оптимизация под задачи**: модели оптимизированы для конкретных юридических задач
- **Выбор модели**: выбор лучшей модели для каждой задачи

#### **Интеграция с контентом**
- **LexisNexis partnership**: интеграция с авторитетным юридическим контентом
- **Citation support**: ответы с цитатами из первичных источников права
- **Верификация**: повышение надежности и проверяемости результатов

#### **Human-in-the-Loop**
- **Экспертное наблюдение**: человеческие эксперты проверяют выводы агентов
- **Сложные сценарии**: особенно важно для неоднозначных случаев
- **Повышение точности**: улучшение общей производительности системы

#### **Continuous Learning**
- **Обучение на взаимодействиях**: система учится на взаимодействиях пользователей
- **Итеративное улучшение**: постоянное уточнение способностей к рассуждению
- **Адаптация к стандартам**: адаптация к изменяющимся юридическим стандартам

### 2.3. Технические особенности

```
┌─────────────────────────────────────────┐
│      Specialized Agent Pool              │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐│
│   │Antitrust│  │Cyber    │  │Fund     ││
│   │  Agent  │  │Security │  │Formation││
│   └────┬────┘  └────┬────┘  └────┬────┘│
└────────┼────────────┼────────────┼─────┘
         │            │            │
         └────────────┼────────────┘
                      │
         ┌────────────▼────────────┐
         │  Planning & Orchestrator │
         │  (Multi-stage planning)  │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  Execution Layer         │
         │  - Task execution        │
         │  - Inter-agent comm      │
         │  - Synthesis             │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  Integration Layer       │
         │  - LexisNexis            │
         │  - Legal databases       │
         │  - Citation verification │
         └────────────┬────────────┘
                      │
         ┌────────────▼────────────┐
         │  Human-in-the-Loop       │
         │  (Review & Supervision)  │
         └─────────────────────────┘
```

### 2.4. Технологический стек (предположительно)

- **LangChain/LangGraph**: для построения агентных систем
- **OpenAI o1, GPT-5**: для рассуждений и планирования
- **Anthropic, Google models**: для специализированных задач
- **Vector databases**: для хранения и поиска юридических документов
- **Stateful workflows**: для управления сложными многоэтапными процессами

---

## 3. Сравнительный анализ

### 3.1. Общие черты

| Аспект | Legora | Harvey AI |
|--------|--------|-----------|
| **Естественный язык** | ✅ Workflows с NLP входом | ✅ Планирование через NLP |
| **Автономное планирование** | ✅ Agentic planning | ✅ Collaborative planning |
| **Интеграции** | ✅ Word add-in, инструменты | ✅ LexisNexis, базы данных |
| **Адаптация** | ✅ Под фирмы | ✅ Под задачи через выбор модели |
| **Human oversight** | ✅ Через collaboration | ✅ Human-in-the-loop |

### 3.2. Различия

| Аспект | Legora | Harvey AI |
|--------|--------|-----------|
| **Архитектура агентов** | Workflows-ориентированная | Мультиагентная с специализацией |
| **Специализация** | Универсальные workflows | Домен-специфичные агенты |
| **Модели** | Не указано явно | Множественные (o1, GPT-5, etc.) |
| **Планирование** | Автономное | Коллаборативное между агентами |
| **Обучение** | Адаптация под фирмы | Continuous learning |

---

## 4. Рекомендации для нашей системы

### 4.1. Что уже реализовано ✅

1. **LangGraph-based мультиагентная система**
   - Специализированные агенты (timeline, key_facts, discrepancy, risk, summary)
   - Supervisor pattern для роутинга
   - Stateful workflows

2. **Интеграции**
   - RAG service для извлечения документов
   - База данных для сохранения результатов
   - Document processor

3. **Обработка ошибок**
   - Fallback механизмы
   - Частичные результаты
   - Error tracking в state

### 4.2. Что можно улучшить на основе анализа

#### **4.2.1. Планирование и автономность (из Legora)**

**Рекомендация**: Добавить слой планирования задач

```python
# Предложение: добавить Planning Agent
class PlanningAgent:
    """
    Агент, который анализирует входную задачу и создает план выполнения
    """
    def plan_analysis(
        self, 
        user_goal: str, 
        documents: List[Document],
        available_agents: List[str]
    ) -> AnalysisPlan:
        """
        Создает план выполнения на основе:
        - Цели пользователя (natural language)
        - Доступных документов
        - Доступных агентов
        
        Returns:
            AnalysisPlan с последовательностью шагов
        """
        pass
```

**Преимущества**:
- Автономное определение необходимых анализов
- Адаптация под разные типы дел
- Более гибкая система

#### **4.2.2. Специализированные агенты (из Harvey AI)**

**Рекомендация**: Расширить специализацию агентов

**Текущее состояние**: Общие агенты для всех типов дел
**Предложение**: Домен-специфичные агенты

```python
# Пример: специализированные агенты
class DomainSpecificAgents:
    """Специализированные агенты для разных юридических доменов"""
    
    # Корпоративное право
    corporate_m_and_a_agent: Agent
    corporate_compliance_agent: Agent
    
    # Договорное право
    contract_review_agent: Agent
    contract_negotiation_agent: Agent
    
    # Судебные дела
    litigation_analysis_agent: Agent
    discovery_agent: Agent
```

**Преимущества**:
- Более точные результаты
- Оптимизация под специфические задачи
- Возможность использования разных моделей для разных доменов

#### **4.2.3. Human-in-the-Loop (из Harvey AI)**

**Рекомендация**: Добавить механизм человеческого надзора

```python
# Предложение: Human Review Layer
class HumanReviewManager:
    """
    Управляет процессом проверки результатов человеком
    """
    def request_review(
        self,
        agent_result: Dict,
        confidence_score: float,
        complexity: str
    ) -> ReviewRequest:
        """
        Запрашивает проверку для:
        - Низкой уверенности агента
        - Высокой сложности задачи
        - Критических результатов
        """
        pass
    
    def incorporate_feedback(
        self,
        review_feedback: Feedback,
        agent_result: Dict
    ) -> Dict:
        """
        Включает обратную связь человека в результат
        """
        pass
```

**Преимущества**:
- Повышение точности
- Снижение рисков
- Обучение на обратной связи

#### **4.2.4. Continuous Learning (из Harvey AI)**

**Рекомендация**: Добавить механизм обучения на взаимодействиях

```python
# Предложение: Learning System
class AgentLearningSystem:
    """
    Система обучения агентов на основе взаимодействий
    """
    def collect_interaction(
        self,
        agent_name: str,
        input_data: Dict,
        output: Dict,
        user_feedback: Optional[Feedback]
    ):
        """
        Собирает данные о взаимодействиях для обучения
        """
        pass
    
    def update_agent_prompts(
        self,
        agent_name: str,
        learned_patterns: List[Pattern]
    ):
        """
        Обновляет промпты агентов на основе выученных паттернов
        """
        pass
```

**Преимущества**:
- Улучшение со временем
- Адаптация к специфике фирмы
- Повышение релевантности результатов

#### **4.2.5. Интеграция с авторитетными источниками (из Harvey AI)**

**Рекомендация**: Интегрировать юридические базы данных

```python
# Предложение: Legal Knowledge Integration
class LegalKnowledgeIntegrator:
    """
    Интеграция с авторитетными юридическими источниками
    """
    def search_case_law(
        self,
        query: str,
        jurisdiction: str
    ) -> List[Case]:
        """
        Поиск в базе прецедентов
        """
        pass
    
    def verify_citation(
        self,
        citation: str
    ) -> CitationVerification:
        """
        Верификация цитат
        """
        pass
    
    def get_statute_reference(
        self,
        topic: str
    ) -> List[Statute]:
        """
        Получение ссылок на статуты
        """
        pass
```

**Преимущества**:
- Повышение надежности
- Поддержка цитатами
- Верифицируемые результаты

#### **4.2.6. Workflow Customization (из Legora)**

**Рекомендация**: Позволить настраивать workflows под фирмы

```python
# Предложение: Customizable Workflows
class WorkflowCustomizer:
    """
    Кастомизация workflows под специфику фирмы
    """
    def create_custom_workflow(
        self,
        firm_id: str,
        workflow_steps: List[WorkflowStep],
        custom_prompts: Dict[str, str]
    ) -> CustomWorkflow:
        """
        Создает кастомный workflow для фирмы
        """
        pass
    
    def apply_firm_protocols(
        self,
        workflow: Workflow,
        firm_protocols: FirmProtocols
    ) -> Workflow:
        """
        Применяет протоколы фирмы к workflow
        """
        pass
```

**Преимущества**:
- Адаптация под каждую фирму
- Соответствие внутренним стандартам
- Повышение принятия систем

#### **4.2.7. Multi-Model Strategy (из Harvey AI)**

**Рекомендация**: Использовать разные модели для разных задач

```python
# Предложение: Model Selection Strategy
class ModelSelector:
    """
    Выбор оптимальной модели для каждой задачи
    """
    def select_model(
        self,
        task_type: str,
        complexity: str,
        requirements: TaskRequirements
    ) -> LLM:
        """
        Выбирает лучшую модель для задачи:
        - GPT-4/o1 для сложных рассуждений
        - GPT-3.5 для простых задач
        - Claude для длинных документов
        """
        pass
```

**Преимущества**:
- Оптимизация стоимости
- Повышение качества
- Баланс скорости и точности

---

## 5. Приоритеты внедрения

### 5.1. Краткосрочные (1-2 месяца)

1. **Human-in-the-Loop механизм**
   - Критично для production использования
   - Снижает риски ошибок
   - Увеличивает доверие пользователей

2. **Улучшение планирования**
   - Автономное определение необходимых анализов
   - Более интеллектуальная система

3. **Workflow customization**
   - Важно для принятия клиентами
   - Адаптация под фирмы

### 5.2. Среднесрочные (3-6 месяцев)

1. **Интеграция с юридическими базами данных**
   - Повышение надежности
   - Поддержка цитатами

2. **Multi-model strategy**
   - Оптимизация производительности
   - Снижение затрат

3. **Continuous learning**
   - Улучшение со временем
   - Адаптация к специфике

### 5.3. Долгосрочные (6+ месяцев)

1. **Домен-специфичные агенты**
   - Требует значительной работы
   - Высокая специализация

2. **Расширенная интеграция**
   - Microsoft Word add-in
   - Другие юридические инструменты

---

## 6. Технические детали реализации

### 6.1. Planning Agent (на базе LangGraph)

```python
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from app.services.langchain_agents.state import AnalysisState

class PlanningState(TypedDict):
    """State для planning агента"""
    user_goal: str
    documents: List[Document]
    available_agents: List[str]
    analysis_plan: Optional[List[str]]
    reasoning: Optional[str]

def create_planning_agent(llm: ChatOpenAI):
    """Создает planning агента"""
    graph = StateGraph(PlanningState)
    
    def plan_analysis(state: PlanningState):
        # Анализ цели пользователя
        # Определение необходимых анализов
        # Создание плана выполнения
        pass
    
    graph.add_node("plan", plan_analysis)
    graph.add_edge("plan", END)
    
    return graph.compile()
```

### 6.2. Human Review Integration

```python
class ReviewState(TypedDict):
    """State для review процесса"""
    agent_result: Dict
    confidence: float
    review_requested: bool
    human_feedback: Optional[Dict]
    final_result: Optional[Dict]

def create_review_workflow():
    """Создает workflow для human review"""
    graph = StateGraph(ReviewState)
    
    def check_confidence(state: ReviewState):
        if state["confidence"] < 0.7:
            state["review_requested"] = True
        return state
    
    def request_review(state: ReviewState):
        # Отправка запроса на проверку
        pass
    
    def incorporate_feedback(state: ReviewState):
        # Включение обратной связи
        pass
    
    graph.add_node("check", check_confidence)
    graph.add_node("review", request_review)
    graph.add_node("incorporate", incorporate_feedback)
    
    return graph.compile()
```

---

## 7. Заключение

Анализ архитектур Legora и Harvey AI показывает несколько ключевых направлений для улучшения:

1. **Автономное планирование** — добавление слоя планирования для более интеллектуальной системы
2. **Human-in-the-Loop** — критично для production использования
3. **Специализация агентов** — домен-специфичные агенты для повышения точности
4. **Интеграция с базами знаний** — повышение надежности через авторитетные источники
5. **Continuous learning** — адаптация и улучшение со временем
6. **Workflow customization** — адаптация под специфику клиентов

Наша текущая архитектура на базе LangGraph уже предоставляет хорошую основу для этих улучшений. Рекомендуется поэтапное внедрение с приоритетом на Human-in-the-Loop и улучшение планирования.

---

## Ссылки

- [Legora Official Website](https://legora.com)
- [Harvey AI Official Website](https://www.harvey.ai)
- [Legora BusinessWire Announcements](https://www.businesswire.com/news/home/)
- [Harvey AI Blog](https://www.harvey.ai/blog)

---

*Документ создан: 2024-12-16*
*Последнее обновление: 2024-12-16*
