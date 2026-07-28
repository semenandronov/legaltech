"use client";

import { useState, useEffect, useMemo, memo } from "react";
import { cn } from "@/lib/utils";
import {
  Check,
  ChevronUp,
  ChevronDown,
  Loader2,
  FileText,
  Table2,
  Database,
  Scale,
  ScanSearch,
  Search,
  ClipboardCheck,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface ThinkingStep {
  phase: string;
  step: number;
  totalSteps: number;
  content: string;
  status?: "pending" | "running" | "completed" | "error";
  toolName?: string;
}

/** Пошаговый план workflow: статусы синхронизируются с SSE (отдельно от лога событий). */
export interface WorkflowPlanOutlineRow {
  id: string;
  label: string;
  tool?: string;
  status: "pending" | "running" | "completed" | "error";
}

/** Подзадачи из LangChain ``write_todos`` (DeepAgents), отдельно от плана workflow */
export interface WorkflowAgentTodoItem {
  content: string;
  status: string;
}

export interface ToolCallInfo {
  name: string;
  input?: any;
  output?: any;
  status?: "pending" | "running" | "completed" | "error";
}

interface ThinkingBlockProps {
  steps: ThinkingStep[];
  toolCalls?: ToolCallInfo[];
  /** План по шагам с индикаторами (галочка / спиннер / ожидание) */
  planOutline?: WorkflowPlanOutlineRow[];
  /** Заголовок блока плана (например Deep Agents vs шаблон workflow) */
  planOutlineTitle?: string;
  /** Подзадачи агента (SSE ``agent_todos_updated``) */
  agentTodos?: WorkflowAgentTodoItem[];
  isStreaming?: boolean;
  progressPercent?: number;
  workflowStatus?: "running" | "completed" | "failed";
  className?: string;
  defaultOpen?: boolean;
}

// ─── Reasoning phase → natural Russian sentence ──────────────────────────────

/** Подпись типа шага, если текста от бэкенда ещё нет — не путать с «мышлением» модели в токенах API */
const PHASE_LABELS: Record<string, string> = {
  thinking: "Служебный шаг: разбор запроса",
  agent: "Служебный шаг: план агента",
  understanding: "Пошаговый анализ · понимание",
  context: "Пошаговый анализ · контекст",
  reasoning: "Пошаговый анализ · логика",
  synthesis: "Пошаговый анализ · синтез",
  counterarguments: "Пошаговый анализ · контраргументы",
  legal_analysis: "Пошаговый анализ · право",
  precedents: "Пошаговый анализ · практика",
  reflection: "Проверка ответа",
  citation_verification: "Верификация цитат",
  tool_call: "Вызов инструмента",
  /** Текст из API (reasoning_content), если провайдер отдаёт */
  model_reasoning: "Рассуждение модели (ответ API)",
  statement_plan: "План анализа выписки",
  statement_tool: "Запрос к данным",
  statement_critique: "Проверка результата",
  statement_revise: "Уточнение плана",
  statement_synthesize: "Формулировка ответа",
};

// ─── Build natural sentence from tool name + input ───────────────────────────

function buildStepLabel(name: string, input?: any): string {
  const inp = input || {};
  const q = inp.query || inp.filename || inp.doc_name || inp.document_name;
  const short = (s: string, n = 55) => s.length > n ? s.substring(0, n) + "…" : s;

  switch (name) {
    case "search_in_documents":
      // Не дублируем текст вопроса юриста в колонке ответа — иначе кажется «мигание» своего же запроса.
      return "Ищу в документах дела";
    case "analyze_all_documents":
      return "Анализирую все документы дела";
    case "search_garant":
      return "Поиск в ГАРАНТ";
    case "get_law_article":
      return inp.article_id ? `Получаю статью ${inp.article_id}` : "Получаю статью закона";
    case "get_document":
      return q ? `Читаю документ «${short(q)}»` : "Читаю документ";
    case "extract_structured_data":
      return "Извлекаю структурированные данные из документов";
    case "compare_documents":
      return "Сравниваю документы";
    case "validate_with_playbook":
      return "Проверяю документ по Playbook";
    case "get_user_playbooks":
      return "Загружаю список Playbooks";
    case "generate_document":
      return inp.template_name ? `Создаю документ по шаблону «${short(inp.template_name)}»` : "Создаю документ";
    case "create_document":
      return inp.title ? `Создаю документ «${short(inp.title)}»` : "Создаю документ";
    case "edit_document":
      return "Редактирую документ";
    case "calculate":
      return inp.expression ? `Вычисляю: ${short(inp.expression, 45)}` : "Выполняю расчёт";
    case "get_current_date":
      return "Получаю текущую дату";
    case "list_templates":
      return "Просматриваю доступные шаблоны";
    case "search_web":
    case "web_research":
      return "Поиск в интернете";
    case "create_tabular_review":
      return "Создаю табличный анализ";
    case "run_playbook_check":
      return "Проверяю документ по Playbook";
    default:
      return name.replace(/_/g, " ");
  }
}

// ─── Step row (Harvey style) ─────────────────────────────────────────────────

const StepRow = memo(({
  label,
  status,
  details,
  toolName,
  isLast,
}: {
  label: string;
  status: "pending" | "running" | "completed" | "error";
  details?: string;
  toolName?: string;
  isLast: boolean;
}) => {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={cn(!isLast && "mb-1")}>
      <div
        className={cn(
          "flex items-start gap-2.5 py-1 px-0.5",
          details && "cursor-pointer"
        )}
        onClick={() => details && setExpanded(!expanded)}
      >
        {/* Status mark */}
        <div className="mt-0.5 flex-shrink-0 w-4 h-4 flex items-center justify-center">
          {status === "completed" && (
            <Check className="w-3.5 h-3.5 text-emerald-500" strokeWidth={2.5} />
          )}
          {status === "running" && (
            <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin" />
          )}
          {status === "pending" && (
            <div className="w-2.5 h-2.5 rounded-full border border-gray-300" />
          )}
          {status === "error" && (
            <Check className="w-3.5 h-3.5 text-red-400" strokeWidth={2.5} />
          )}
        </div>

        {/* Полный текст шага: переносы и длинные абзацы без обрезки одной строкой */}
        <div className="flex-1 min-w-0">
          {toolName && (
            <span
              className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium mr-2 mb-1"
              style={{
                backgroundColor: "var(--color-bg-hover)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text-secondary)",
              }}
            >
              {(() => {
                const { label, icon: Icon } = getToolMeta(toolName);
                return (
                  <>
                    <Icon className="w-3 h-3 mr-1" />
                    {label}
                  </>
                );
              })()}
            </span>
          )}
          <span className={cn(
            "text-sm leading-snug min-w-0 whitespace-pre-wrap break-words",
            status === "completed" ? "text-gray-600" :
            status === "running" ? "text-gray-900 font-medium" :
            "text-gray-400"
          )}>
            {label}
          </span>
        </div>
      </div>

      {/* Expanded raw output */}
      {expanded && details && (
        <div className="ml-7 mb-1.5 pl-3 border-l-2 border-gray-200">
          <pre className="text-xs text-gray-500 whitespace-pre-wrap break-words font-sans leading-relaxed max-h-[min(50vh,24rem)] overflow-y-auto">
            {details}
          </pre>
        </div>
      )}
    </div>
  );
});

StepRow.displayName = "StepRow";

const phaseTitle = (phase: string): string => {
  const p = (phase || "").toLowerCase();
  if (p.includes("plan")) return "Планирование";
  if (p.includes("validation") || p.includes("review")) return "Проверка";
  if (p.includes("complete") || p.includes("final")) return "Финализация";
  if (p.includes("step") || p.includes("workflow")) return "Выполнение";
  return "Ход выполнения";
};

const TOOL_META: Record<string, { label: string; icon: LucideIcon }> = {
  document_draft: { label: "Черновик", icon: FileText },
  tabular_review: { label: "Таблица", icon: Table2 },
  legal_db: { label: "Правовая база", icon: Scale },
  extract_entities: { label: "Сущности", icon: ScanSearch },
  summarize: { label: "Суммаризация", icon: ClipboardCheck },
  rag: { label: "RAG", icon: Search },
  playbook_check: { label: "Проверка Playbook", icon: Database },
};

const normalizeToolName = (toolName?: string): string => (toolName || "").trim().toLowerCase();

const getToolMeta = (toolName?: string): { label: string; icon: LucideIcon } => {
  const normalized = normalizeToolName(toolName);
  return TOOL_META[normalized] || { label: toolName || "Инструмент", icon: Wrench };
};

// ─── Main ThinkingBlock component ────────────────────────────────────────────

function mapAgentTodoStatus(raw: string): "pending" | "running" | "completed" | "error" {
  let s = (raw || "").toLowerCase().trim();
  if (s.includes(".")) s = s.split(".").pop() || s;
  if (s === "completed" || s === "complete" || s === "done" || s.includes("completed")) return "completed";
  if (s === "in_progress" || s === "running" || s === "active" || s.includes("progress")) return "running";
  if (s === "failed" || s.includes("fail") || s.includes("error") || s.includes("cancel")) return "error";
  return "pending";
}

export const ThinkingBlock = memo(({
  steps,
  toolCalls,
  planOutline,
  planOutlineTitle,
  agentTodos,
  isStreaming = false,
  progressPercent,
  workflowStatus,
  className,
  defaultOpen = true,
}: ThinkingBlockProps) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [hasAutoClosed, setHasAutoClosed] = useState(false);
  const [startTime] = useState(() => Date.now());
  const [duration, setDuration] = useState(0);

  // Track duration while streaming
  useEffect(() => {
    if (!isStreaming) return;
    const interval = setInterval(() => {
      setDuration(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [isStreaming, startTime]);

  // Auto-collapse 2s after streaming ends
  useEffect(() => {
    if (!isStreaming && (steps.length > 0 || (toolCalls && toolCalls.length > 0)) && isOpen && !hasAutoClosed) {
      const t = setTimeout(() => { setIsOpen(false); setHasAutoClosed(true); }, 2000);
      return () => clearTimeout(t);
    }
  }, [isStreaming, steps.length, toolCalls, isOpen, hasAutoClosed]);

  // Build unified step list
  type UStep = {
    id: string;
    phase: string;
    label: string;
    status: "pending" | "running" | "completed" | "error";
    details?: string;
    toolName?: string;
  };

  const detectToolName = (text: string): string | undefined => {
    const src = (text || "").toLowerCase();
    const tools = [
      "document_draft",
      "playbook_check",
      "tabular_review",
      "extract_entities",
      "legal_db",
      "summarize",
      "rag",
    ];
    return tools.find((t) => src.includes(t));
  };

  const unifiedSteps = useMemo((): UStep[] => {
    const result: UStep[] = [];

    steps?.forEach((rs) => {
      const phaseHint = PHASE_LABELS[rs.phase] || rs.phase;
      const raw = (rs.content || "").trim();
      // Полный текст шага — без искусственного «…» в одной строке (раньше резали ~220 символов).
      const label = raw.length > 0 ? raw : phaseHint;
      result.push({
        id: `r-${rs.phase}-${rs.step}`,
        phase: rs.phase || "",
        label,
        status: rs.status || "completed",
        details: undefined,
        toolName: rs.toolName || detectToolName(`${label} ${rs.phase}`),
      });
    });

    toolCalls?.forEach((tc, i) => {
      result.push({
        id: `t-${tc.name}-${i}`,
        phase: "tool_call",
        label: `Действие · ${buildStepLabel(tc.name, tc.input)}`,
        status: tc.status || "completed",
        details: tc.output ? (typeof tc.output === "string" ? tc.output : JSON.stringify(tc.output, null, 2)) : undefined,
        toolName: tc.name,
      });
    });

    return result;
  }, [steps, toolCalls]);

  const hasContent =
    steps.length > 0 ||
    (toolCalls && toolCalls.length > 0) ||
    (planOutline && planOutline.length > 0) ||
    (agentTodos && agentTodos.length > 0);
  const shouldShowForRunningWorkflow = workflowStatus === "running";
  if (!hasContent && !isStreaming && !shouldShowForRunningWorkflow) return null;

  const totalCount = unifiedSteps.length;
  /** Только реальный workflow/UI плана или явная фаза `workflow*`. Не матчим рус. «шаг/план» в тексте — иначе обычный чат дела показывает «Workflow выполняется». */
  const workflowMode =
    (planOutline && planOutline.length > 0) ||
    (agentTodos && agentTodos.length > 0) ||
    (steps || []).some((s) => {
      const p = String(s.phase || "").toLowerCase();
      return p === "workflow" || p.startsWith("workflow_");
    });
  const completedCount = unifiedSteps.filter((s) => s.status === "completed").length;
  const hasTerminalWorkflowStatus = workflowStatus === "completed" || workflowStatus === "failed";
  const isWorkflowFinished = hasTerminalWorkflowStatus;
  const progress = typeof progressPercent === "number"
    ? Math.max(0, Math.min(100, Math.round(progressPercent)))
    : (totalCount > 0 ? Math.max(6, Math.round((completedCount / totalCount) * 100)) : (isStreaming ? 12 : 100));
  const activeSteps = unifiedSteps.filter((s) => s.status === "running" || s.status === "pending");
  const doneSteps = unifiedSteps.filter((s) => s.status === "completed" || s.status === "error");
  const workflowCardStyle = workflowMode
    ? {
        borderColor: "var(--color-border)",
        background: "linear-gradient(180deg, var(--color-bg-secondary) 0%, var(--color-bg-elevated) 100%)",
        boxShadow: "var(--shadow-sm)",
      }
    : undefined;

  return (
    <div
      className={cn(
        "mb-3 select-none",
        workflowMode && "rounded-xl border p-3",
        className
      )}
      style={workflowCardStyle}
    >
      {/* Header */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "flex items-center gap-1.5 py-1 text-sm text-gray-500 hover:text-gray-700 transition-colors w-full",
          workflowMode && "justify-between"
        )}
      >
        <span className="flex items-center gap-1.5 min-w-0">
          {isStreaming || (workflowMode && !isWorkflowFinished) ? (
            <>
              <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin flex-shrink-0" />
              <span className={cn("font-medium text-gray-600")} style={workflowMode ? { color: "var(--color-text-primary)" } : undefined}>
                {workflowMode ? "Workflow выполняется" : "Работаю"}
                {totalCount > 0 ? ` · ${totalCount} ${totalCount === 1 ? "шаг" : totalCount < 5 ? "шага" : "шагов"}` : "..."}
              </span>
              {duration > 0 && (
                <span className="text-gray-400 font-normal">{duration} с</span>
              )}
            </>
          ) : (
            <span className={cn("font-medium")} style={workflowMode ? { color: "var(--color-text-primary)" } : undefined}>
              {workflowMode ? "Workflow завершен" : `Завершено за ${totalCount} ${totalCount === 1 ? "шаг" : totalCount < 5 ? "шага" : "шагов"}`}
              {duration > 0 && (
                <span className="text-gray-400 font-normal ml-1">· {duration} с</span>
              )}
            </span>
          )}
        </span>
        <span className="flex items-center gap-2 flex-shrink-0">
          {workflowMode && (
            <span
              className={cn(
                "text-[11px] px-2 py-0.5 rounded-full border",
                isStreaming ? "" : ""
              )}
              style={
                (isStreaming || !isWorkflowFinished)
                  ? {
                      backgroundColor: "var(--color-info-bg)",
                      color: "var(--color-info)",
                      borderColor: "color-mix(in srgb, var(--color-info) 30%, var(--color-border))",
                    }
                  : {
                      backgroundColor: "var(--color-success-bg)",
                      color: "var(--color-success)",
                      borderColor: "color-mix(in srgb, var(--color-success) 30%, var(--color-border))",
                    }
              }
            >
              {(isStreaming || !isWorkflowFinished) ? `${progress}%` : "100%"}
            </span>
          )}
          {isOpen ? (
            <ChevronUp className="w-3.5 h-3.5 text-gray-400 ml-0.5" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5 text-gray-400 ml-0.5" />
          )}
        </span>
      </button>

      {workflowMode && (
        <div className="mt-2 mb-1 h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: "var(--color-border-subtle)" }}>
          <div
            className={cn("h-full rounded-full transition-all duration-500")}
            style={{
              backgroundColor:
                workflowStatus === "failed"
                  ? "var(--color-error)"
                  : isStreaming
                    ? "var(--color-info)"
                    : "var(--color-success)",
              width: `${(isStreaming || !isWorkflowFinished) ? progress : 100}%`,
            }}
          />
        </div>
      )}

      {workflowMode && planOutline && planOutline.length > 0 && (
        <div className="mt-3 mb-1 space-y-0.5">
          <div
            className="text-[11px] font-medium uppercase tracking-wide mb-2"
            style={{ color: "var(--color-text-muted)" }}
          >
            {planOutlineTitle || "План выполнения"}
          </div>
          <div className="pl-1 border-l-2" style={{ borderColor: "var(--color-accent)" }}>
            {planOutline.map((row, i) => (
              <StepRow
                key={`plan-${row.id}-${i}`}
                label={`${i + 1}. ${row.label}`}
                status={row.status}
                details={undefined}
                toolName={row.tool}
                isLast={i === planOutline.length - 1}
              />
            ))}
          </div>
        </div>
      )}

      {workflowMode && agentTodos && agentTodos.length > 0 && (
        <div className="mt-3 mb-1 space-y-0.5">
          <div
            className="text-[11px] font-medium uppercase tracking-wide mb-2"
            style={{ color: "var(--color-text-muted)" }}
          >
            Подзадачи агента
          </div>
          <div className="pl-1 border-l-2" style={{ borderColor: "var(--color-border)" }}>
            {agentTodos.map((row, i) => (
              <StepRow
                key={`atodo-${i}-${row.content.slice(0, 24)}`}
                label={row.content}
                status={mapAgentTodoStatus(row.status)}
                details={undefined}
                toolName={undefined}
                isLast={i === agentTodos.length - 1}
              />
            ))}
          </div>
        </div>
      )}

      {/* Steps list */}
      {isOpen && (
        <div className={cn("mt-1.5 ml-0.5", workflowMode && "mt-2.5 ml-0")}>
          {workflowMode ? (
            <div className="space-y-3">
              {activeSteps.length > 0 && (
                <div>
                  <div
                    className="text-[11px] font-medium uppercase tracking-wide mb-1.5"
                    style={{ color: "var(--color-text-muted)" }}
                  >
                    Сейчас
                  </div>
                  <div className="pl-2 border-l-2" style={{ borderColor: "var(--color-border)" }}>
                    {activeSteps.map((step, idx) => (
                      <StepRow
                        key={step.id}
                        label={`${phaseTitle(step.phase)} · ${step.label}`}
                        status={step.status}
                        details={step.details}
                        toolName={step.toolName}
                        isLast={idx === activeSteps.length - 1}
                      />
                    ))}
                  </div>
                </div>
              )}

              {doneSteps.length > 0 && (
                <div>
                  <div
                    className="text-[11px] font-medium uppercase tracking-wide mb-1.5"
                    style={{ color: "var(--color-text-muted)" }}
                  >
                    Завершено
                  </div>
                  <div className="pl-2 border-l-2" style={{ borderColor: "var(--color-border-subtle)" }}>
                    {doneSteps.map((step, idx) => (
                      <StepRow
                        key={step.id}
                        label={`${phaseTitle(step.phase)} · ${step.label}`}
                        status={step.status}
                        details={step.details}
                        toolName={step.toolName}
                        isLast={idx === doneSteps.length - 1}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            unifiedSteps.map((step, idx) => (
              <StepRow
                key={step.id}
                label={step.label}
                status={step.status}
                details={step.details}
                toolName={step.toolName}
                isLast={idx === unifiedSteps.length - 1}
              />
            ))
          )}

          {/* Placeholder spinner */}
          {isStreaming && unifiedSteps.length > 0 && unifiedSteps.every(s => s.status === "completed") && (
            <div className="flex items-center gap-2.5 py-1 px-0.5">
              <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin flex-shrink-0" />
              <span className="text-sm text-gray-400">Обрабатываю...</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

ThinkingBlock.displayName = "ThinkingBlock";

export default ThinkingBlock;
