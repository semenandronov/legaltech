"use client";

import { useState, useEffect, useMemo, memo } from "react";
import { cn } from "@/lib/utils";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Sparkles,
  Search,
  FileText,
  Scale,
  Globe,
  PenTool,
  Brain,
  Shield,
  BarChart3,
} from "lucide-react";

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

// ─── Tool name → Russian label + icon ───────────────────────────────────────

const TOOL_CONFIG: Record<string, { label: string; icon: typeof Search }> = {
  search_in_documents: { label: "Поиск в документах дела", icon: Search },
  analyze_all_documents: { label: "Анализ всех документов", icon: BarChart3 },
  search_garant: { label: "Поиск в ГАРАНТ", icon: Scale },
  create_document: { label: "Создание документа", icon: FileText },
  edit_document: { label: "Редактирование документа", icon: PenTool },
  search_web: { label: "Поиск в интернете", icon: Globe },
  create_tabular_review: { label: "Создание таблицы", icon: BarChart3 },
  run_playbook_check: { label: "Проверка по Playbook", icon: Shield },
};

// ─── Reasoning phase → Russian label ────────────────────────────────────────

const PHASE_LABELS: Record<string, string> = {
  thinking: "Глубокий анализ вопроса",
  agent: "Выбор стратегии ответа",
  understanding: "Понимание вопроса",
  context: "Анализ контекста",
  reasoning: "Рассуждение",
  synthesis: "Синтез ответа",
  reflection: "Проверка качества ответа",
  citation_verification: "Проверка цитат",
};

// ─── Unified step type ──────────────────────────────────────────────────────

interface UnifiedStep {
  id: string;
  label: string;
  status: "pending" | "running" | "completed" | "error";
  icon: typeof Search;
  details?: string;
  expandable: boolean;
  type: "reasoning" | "tool";
}

// ─── Helper: parse tool output for short summary ────────────────────────────

function getToolSummary(name: string, output?: any): string | undefined {
  if (!output) return undefined;
  const text = typeof output === "string" ? output : JSON.stringify(output);

  if (name === "search_in_documents") {
    const match = text.match(/Найдено (\d+)/);
    if (match) return `${match[1]} результатов`;
    // Count "Источник" occurrences
    const sources = (text.match(/Источник/g) || []).length;
    if (sources > 0) return `${sources} источников`;
  }

  if (name === "analyze_all_documents") {
    const match = text.match(/(\d+)\s*(документ|файл)/i);
    if (match) return `${match[1]} документов`;
  }

  if (name === "search_garant") {
    const match = text.match(/найден|статья|закон/i);
    if (match) return "найдено";
  }

  // Truncate for general display
  if (text.length > 80) return text.substring(0, 80) + "…";
  return text;
}

// ─── Expandable step row ────────────────────────────────────────────────────

const StepRow = memo(({
  step,
  isLast
}: {
  step: UnifiedStep;
  isLast: boolean;
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const Icon = step.icon;

  const statusIcon = (() => {
    switch (step.status) {
      case "completed":
        return <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />;
      case "running":
        return <Loader2 className="w-4 h-4 text-blue-500 animate-spin flex-shrink-0" />;
      case "error":
        return <CheckCircle2 className="w-4 h-4 text-red-500 flex-shrink-0" />;
      default:
        return (
          <div className="w-4 h-4 rounded-full border-2 border-gray-300 flex-shrink-0" />
        );
    }
  })();

  return (
    <div className={cn(!isLast && "mb-0.5")}>
      {/* Main row */}
      <div
        className={cn(
          "flex items-center gap-2.5 py-1.5 px-1 rounded-md transition-colors",
          step.expandable && step.details && "cursor-pointer hover:bg-gray-50",
          step.status === "running" && "text-blue-700"
        )}
        onClick={() => {
          if (step.expandable && step.details) {
            setIsExpanded(!isExpanded);
          }
        }}
      >
        {/* Status icon */}
        {statusIcon}

        {/* Tool/Phase icon */}
        <Icon className={cn(
          "w-3.5 h-3.5 flex-shrink-0",
          step.status === "completed" ? "text-gray-400" :
          step.status === "running" ? "text-blue-500" : "text-gray-300"
        )} />

        {/* Label */}
        <span className={cn(
          "text-sm flex-1",
          step.status === "completed" ? "text-gray-600" :
          step.status === "running" ? "text-gray-800 font-medium" : "text-gray-400"
        )}>
          {step.label}
        </span>

        {/* Expand chevron */}
        {step.expandable && step.details && (
          isExpanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
          )
        )}
      </div>

      {/* Expanded details */}
      {isExpanded && step.details && (
        <div className="ml-9 mt-1 mb-2 pl-3 border-l-2 border-gray-200">
          <pre className="text-xs text-gray-500 whitespace-pre-wrap break-words font-sans leading-relaxed max-h-32 overflow-y-auto">
            {step.details}
          </pre>
        </div>
      )}
    </div>
  );
});

StepRow.displayName = "StepRow";

// ─── Main ThinkingBlock component ───────────────────────────────────────────

export const ThinkingBlock = memo(({
  steps,
  toolCalls,
  isStreaming = false,
  className,
  defaultOpen = true
}: ThinkingBlockProps) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [hasAutoClosed, setHasAutoClosed] = useState(false);
  const [duration, setDuration] = useState(0);
  const [startTime] = useState(() => Date.now());

  // Track duration
  useEffect(() => {
    if (isStreaming) {
      const interval = setInterval(() => {
        setDuration(Math.floor((Date.now() - startTime) / 1000));
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [isStreaming, startTime]);

  // Auto-collapse after streaming ends
  useEffect(() => {
    if (!isStreaming && (steps.length > 0 || (toolCalls && toolCalls.length > 0)) && isOpen && !hasAutoClosed) {
      const timer = setTimeout(() => {
        setIsOpen(false);
        setHasAutoClosed(true);
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [isStreaming, steps.length, toolCalls, isOpen, hasAutoClosed]);

  // Build unified step list
  const unifiedSteps = useMemo((): UnifiedStep[] => {
    const result: UnifiedStep[] = [];

    // Add reasoning steps
    if (steps) {
      steps.forEach((rs) => {
        result.push({
          id: `r-${rs.phase}-${rs.step}`,
          label: PHASE_LABELS[rs.phase] || rs.content || rs.phase,
          status: "completed",
          icon: rs.phase === "thinking" ? Brain :
                rs.phase === "reflection" ? Shield :
                rs.phase === "citation_verification" ? Scale :
                Brain,
          details: rs.content && rs.content !== (PHASE_LABELS[rs.phase] || rs.phase) ? rs.content : undefined,
          expandable: !!(rs.content && rs.content.length > 50),
          type: "reasoning",
        });
      });
    }

    // Add tool calls
    if (toolCalls) {
      toolCalls.forEach((tc, i) => {
        const config = TOOL_CONFIG[tc.name] || { label: tc.name, icon: Search };
        const summary = getToolSummary(tc.name, tc.output);
        const label = summary && tc.status === "completed"
          ? `${config.label} — ${summary}`
          : config.label;

        result.push({
          id: `t-${tc.name}-${i}`,
          label,
          status: tc.status || "completed",
          icon: config.icon,
          details: tc.output ? (typeof tc.output === "string" ? tc.output : JSON.stringify(tc.output, null, 2)) : undefined,
          expandable: !!tc.output,
          type: "tool",
        });
      });
    }

    return result;
  }, [steps, toolCalls]);

  // Don't render if nothing to show
  const hasContent = steps.length > 0 || (toolCalls && toolCalls.length > 0);
  if (!hasContent && !isStreaming) {
    return null;
  }

  const completedCount = unifiedSteps.filter(s => s.status === "completed").length;
  const totalCount = unifiedSteps.length;

  return (
    <div className={cn("mb-4", className)}>
      {/* Header / trigger */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "w-full flex items-center gap-2.5 px-3 py-2 rounded-lg transition-all",
          "hover:bg-gray-50 group text-left",
          "border border-transparent",
          isStreaming && "border-blue-100 bg-blue-50/30"
        )}
      >
        {/* Animated icon */}
        {isStreaming ? (
          <div className="relative">
            <Sparkles className="w-4 h-4 text-blue-500 animate-pulse" />
          </div>
        ) : (
          <Brain className="w-4 h-4 text-gray-400" />
        )}

        {/* Label */}
        <span className={cn(
          "text-sm font-medium flex-1",
          isStreaming ? "text-blue-700" : "text-gray-500"
        )}>
          {isStreaming ? (
            <span className="inline-flex items-center gap-1.5">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-blue-500"></span>
              </span>
              Думаю...
            </span>
          ) : (
            <span>
              Рассуждение
              {duration > 0 && (
                <span className="text-gray-400 font-normal ml-1">
                  {duration} сек
                </span>
              )}
            </span>
          )}
        </span>

        {/* Step counter */}
        {totalCount > 0 && (
          <span className="text-xs text-gray-400">
            {completedCount}/{totalCount}
          </span>
        )}

        {/* Chevron */}
        <ChevronDown
          className={cn(
            "w-4 h-4 text-gray-400 transition-transform duration-200",
            !isOpen && "-rotate-90"
          )}
        />
      </button>

      {/* Steps list */}
      {isOpen && (
        <div className="mt-1 ml-1 pl-3 border-l-2 border-gray-100">
          {unifiedSteps.map((step, idx) => (
            <StepRow
              key={step.id}
              step={step}
              isLast={idx === unifiedSteps.length - 1}
            />
          ))}

          {/* Placeholder when streaming and waiting for next step */}
          {isStreaming && unifiedSteps.every(s => s.status === "completed") && (
            <div className="flex items-center gap-2.5 py-1.5 px-1">
              <Loader2 className="w-4 h-4 text-blue-400 animate-spin flex-shrink-0" />
              <div className="w-3.5 h-3.5" />
              <span className="text-sm text-gray-400 animate-pulse">
                Обрабатываю...
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

ThinkingBlock.displayName = "ThinkingBlock";

export default ThinkingBlock;
