"use client";

import { useState, useEffect, useMemo, memo } from "react";
import { cn } from "@/lib/utils";
import { Check, ChevronUp, ChevronDown, Loader2 } from "lucide-react";

export interface ThinkingStep {
  phase: string;
  step: number;
  totalSteps: number;
  content: string;
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
  isStreaming?: boolean;
  className?: string;
  defaultOpen?: boolean;
}

// ─── Reasoning phase → natural Russian sentence ──────────────────────────────

const PHASE_LABELS: Record<string, string> = {
  thinking: "Анализирую вопрос",
  agent: "Выбираю стратегию",
  understanding: "Разбираю запрос",
  context: "Изучаю контекст",
  reasoning: "Формирую логику ответа",
  synthesis: "Составляю ответ",
  reflection: "Проверяю качество ответа",
  citation_verification: "Верифицирую цитаты",
};

// ─── Build natural sentence from tool name + input ───────────────────────────

function buildStepLabel(name: string, input?: any): string {
  const inp = input || {};
  const q = inp.query || inp.filename || inp.doc_name || inp.document_name;
  const short = (s: string, n = 55) => s.length > n ? s.substring(0, n) + "…" : s;

  switch (name) {
    case "search_in_documents":
      return q ? `Ищу в документах: «${short(q)}»` : "Ищу в документах дела";
    case "analyze_all_documents":
      return "Анализирую все документы дела";
    case "search_garant":
      return q ? `Ищу в ГАРАНТ: «${short(q)}»` : "Поиск в ГАРАНТ";
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
      return q ? `Ищу в интернете: «${short(q)}»` : "Поиск в интернете";
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
  isLast,
}: {
  label: string;
  status: "pending" | "running" | "completed" | "error";
  details?: string;
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

        {/* Label */}
        <span className={cn(
          "text-sm leading-snug flex-1",
          status === "completed" ? "text-gray-600" :
          status === "running" ? "text-gray-900 font-medium" :
          "text-gray-400"
        )}>
          {label}
        </span>
      </div>

      {/* Expanded raw output */}
      {expanded && details && (
        <div className="ml-7 mb-1.5 pl-3 border-l-2 border-gray-200">
          <pre className="text-xs text-gray-400 whitespace-pre-wrap break-words font-sans leading-relaxed max-h-28 overflow-y-auto">
            {details}
          </pre>
        </div>
      )}
    </div>
  );
});

StepRow.displayName = "StepRow";

// ─── Main ThinkingBlock component ────────────────────────────────────────────

export const ThinkingBlock = memo(({
  steps,
  toolCalls,
  isStreaming = false,
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
  type UStep = { id: string; label: string; status: "pending" | "running" | "completed" | "error"; details?: string };

  const unifiedSteps = useMemo((): UStep[] => {
    const result: UStep[] = [];

    steps?.forEach((rs) => {
      result.push({
        id: `r-${rs.phase}-${rs.step}`,
        label: PHASE_LABELS[rs.phase] || rs.content || rs.phase,
        status: "completed",
        details: rs.content && rs.content !== (PHASE_LABELS[rs.phase] || rs.phase) ? rs.content : undefined,
      });
    });

    toolCalls?.forEach((tc, i) => {
      result.push({
        id: `t-${tc.name}-${i}`,
        label: buildStepLabel(tc.name, tc.input),
        status: tc.status || "completed",
        details: tc.output ? (typeof tc.output === "string" ? tc.output : JSON.stringify(tc.output, null, 2)) : undefined,
      });
    });

    return result;
  }, [steps, toolCalls]);

  const hasContent = steps.length > 0 || (toolCalls && toolCalls.length > 0);
  if (!hasContent && !isStreaming) return null;

  const totalCount = unifiedSteps.length;

  return (
    <div className={cn("mb-3 select-none", className)}>
      {/* Header */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 py-1 text-sm text-gray-500 hover:text-gray-700 transition-colors"
      >
        {isStreaming ? (
          <>
            <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin flex-shrink-0" />
            <span className="font-medium text-gray-600">
              Работаю{totalCount > 0 ? ` · ${totalCount} ${totalCount === 1 ? "шаг" : totalCount < 5 ? "шага" : "шагов"}` : "..."}
            </span>
            {duration > 0 && (
              <span className="text-gray-400 font-normal">{duration} с</span>
            )}
          </>
        ) : (
          <span className="font-medium">
            Завершено за {totalCount} {totalCount === 1 ? "шаг" : totalCount < 5 ? "шага" : "шагов"}
            {duration > 0 && (
              <span className="text-gray-400 font-normal ml-1">· {duration} с</span>
            )}
          </span>
        )}
        {isOpen ? (
          <ChevronUp className="w-3.5 h-3.5 text-gray-400 ml-0.5" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 text-gray-400 ml-0.5" />
        )}
      </button>

      {/* Steps list */}
      {isOpen && (
        <div className="mt-1.5 ml-0.5">
          {unifiedSteps.map((step, idx) => (
            <StepRow
              key={step.id}
              label={step.label}
              status={step.status}
              details={step.details}
              isLast={idx === unifiedSteps.length - 1}
            />
          ))}

          {/* Placeholder spinner */}
          {isStreaming && unifiedSteps.every(s => s.status === "completed") && (
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
