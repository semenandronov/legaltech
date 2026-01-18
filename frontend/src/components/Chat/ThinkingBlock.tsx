"use client";

import { useState, useEffect, memo } from "react";
import { cn } from "@/lib/utils";
import { 
  Brain, 
  ChevronDown, 
  Search, 
  Lightbulb, 
  CheckCircle2,
  Loader2,
  Sparkles
} from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/UI/collapsible";

export interface ThinkingStep {
  phase: string;
  step: number;
  totalSteps: number;
  content: string;
}

interface ThinkingBlockProps {
  steps: ThinkingStep[];
  isStreaming?: boolean;
  className?: string;
  defaultOpen?: boolean;
}

const PHASE_CONFIG: Record<string, { 
  icon: typeof Brain; 
  label: string; 
  color: string;
  bgColor: string;
}> = {
  understanding: {
    icon: Brain,
    label: "Понимание вопроса",
    color: "text-blue-600",
    bgColor: "bg-blue-50"
  },
  context: {
    icon: Search,
    label: "Анализ контекста",
    color: "text-purple-600",
    bgColor: "bg-purple-50"
  },
  reasoning: {
    icon: Lightbulb,
    label: "Рассуждение",
    color: "text-amber-600",
    bgColor: "bg-amber-50"
  },
  synthesis: {
    icon: CheckCircle2,
    label: "Синтез ответа",
    color: "text-emerald-600",
    bgColor: "bg-emerald-50"
  }
};

const ThinkingStepItem = memo(({ 
  step, 
  isActive, 
  isCompleted 
}: { 
  step: ThinkingStep; 
  isActive: boolean;
  isCompleted: boolean;
}) => {
  const config = PHASE_CONFIG[step.phase] || {
    icon: Brain,
    label: step.phase,
    color: "text-gray-600",
    bgColor: "bg-gray-50"
  };
  
  const Icon = config.icon;
  
  return (
    <div 
      className={cn(
        "flex gap-3 p-3 rounded-lg transition-all duration-300",
        isActive && "bg-gradient-to-r from-blue-50/80 to-purple-50/80 border border-blue-100",
        isCompleted && !isActive && "opacity-80",
        !isActive && !isCompleted && "opacity-50"
      )}
    >
      {/* Icon with status indicator */}
      <div className="relative flex-shrink-0">
        <div 
          className={cn(
            "w-8 h-8 rounded-full flex items-center justify-center transition-all duration-300",
            config.bgColor,
            isActive && "ring-2 ring-blue-200 ring-offset-1"
          )}
        >
          {isActive ? (
            <Loader2 className={cn("w-4 h-4 animate-spin", config.color)} />
          ) : (
            <Icon className={cn("w-4 h-4", config.color)} />
          )}
        </div>
        
        {/* Connecting line */}
        {step.step < step.totalSteps && (
          <div 
            className={cn(
              "absolute top-8 left-1/2 w-0.5 h-4 -translate-x-1/2",
              isCompleted ? "bg-gradient-to-b from-blue-200 to-purple-200" : "bg-gray-200"
            )}
          />
        )}
      </div>
      
      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={cn(
            "text-xs font-medium uppercase tracking-wide",
            config.color
          )}>
            {config.label}
          </span>
          <span className="text-xs text-gray-400">
            {step.step}/{step.totalSteps}
          </span>
        </div>
        
        <p className={cn(
          "text-sm text-gray-700 leading-relaxed",
          isActive && "animate-pulse"
        )}>
          {step.content || (isActive ? "Анализирую..." : "")}
        </p>
      </div>
    </div>
  );
});

ThinkingStepItem.displayName = "ThinkingStepItem";

export const ThinkingBlock = memo(({
  steps,
  isStreaming = false,
  className,
  defaultOpen = true
}: ThinkingBlockProps) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [hasAutoClosed, setHasAutoClosed] = useState(false);
  const [thinkingDuration, setThinkingDuration] = useState(0);
  const [startTime] = useState(() => Date.now());
  
  // Track duration
  useEffect(() => {
    if (isStreaming) {
      const interval = setInterval(() => {
        setThinkingDuration(Math.floor((Date.now() - startTime) / 1000));
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [isStreaming, startTime]);
  
  // Auto-close after streaming ends
  useEffect(() => {
    if (!isStreaming && steps.length > 0 && isOpen && !hasAutoClosed) {
      const timer = setTimeout(() => {
        setIsOpen(false);
        setHasAutoClosed(true);
      }, 1500);
      return () => clearTimeout(timer);
    }
  }, [isStreaming, steps.length, isOpen, hasAutoClosed]);
  
  if (steps.length === 0 && !isStreaming) {
    return null;
  }
  
  const currentStepIndex = steps.length - 1;
  const completedSteps = isStreaming ? currentStepIndex : steps.length;
  
  return (
    <Collapsible
      open={isOpen}
      onOpenChange={setIsOpen}
      className={cn("mb-4", className)}
    >
      <CollapsibleTrigger className="w-full">
        <div 
          className={cn(
            "flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-300",
            "bg-gradient-to-r from-slate-50 to-gray-50",
            "border border-gray-100 hover:border-gray-200",
            "hover:shadow-sm cursor-pointer group"
          )}
        >
          {/* Animated brain icon */}
          <div className="relative">
            <div className={cn(
              "w-9 h-9 rounded-full flex items-center justify-center",
              "bg-gradient-to-br from-blue-100 to-purple-100",
              isStreaming && "animate-pulse"
            )}>
              {isStreaming ? (
                <Sparkles className="w-4 h-4 text-blue-600 animate-spin" style={{ animationDuration: '3s' }} />
              ) : (
                <Brain className="w-4 h-4 text-blue-600" />
              )}
            </div>
            
            {/* Pulsing ring when streaming */}
            {isStreaming && (
              <div className="absolute inset-0 rounded-full border-2 border-blue-300 animate-ping opacity-30" />
            )}
          </div>
          
          {/* Status text */}
          <div className="flex-1 text-left">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-700">
                {isStreaming ? (
                  <>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                      </span>
                      Думаю...
                    </span>
                  </>
                ) : (
                  "Процесс мышления"
                )}
              </span>
              
              {!isStreaming && thinkingDuration > 0 && (
                <span className="text-xs text-gray-400">
                  {thinkingDuration} сек
                </span>
              )}
            </div>
            
            {/* Progress bar */}
            <div className="mt-1.5 h-1 bg-gray-100 rounded-full overflow-hidden">
              <div 
                className={cn(
                  "h-full rounded-full transition-all duration-500",
                  "bg-gradient-to-r from-blue-400 via-purple-400 to-emerald-400",
                  isStreaming && "animate-pulse"
                )}
                style={{ 
                  width: `${(completedSteps / (steps[0]?.totalSteps || 4)) * 100}%` 
                }}
              />
            </div>
          </div>
          
          {/* Chevron */}
          <ChevronDown 
            className={cn(
              "w-5 h-5 text-gray-400 transition-transform duration-300",
              "group-hover:text-gray-600",
              isOpen && "rotate-180"
            )}
          />
        </div>
      </CollapsibleTrigger>
      
      <CollapsibleContent>
        <div 
          className={cn(
            "mt-2 p-4 rounded-xl",
            "bg-gradient-to-b from-white to-gray-50/50",
            "border border-gray-100",
            "space-y-2"
          )}
        >
          {steps.map((step, index) => (
            <ThinkingStepItem
              key={`${step.phase}-${step.step}`}
              step={step}
              isActive={isStreaming && index === currentStepIndex}
              isCompleted={index < completedSteps}
            />
          ))}
          
          {/* Placeholder for next step when streaming */}
          {isStreaming && steps.length < (steps[0]?.totalSteps || 4) && (
            <div className="flex gap-3 p-3 opacity-30">
              <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center">
                <Loader2 className="w-4 h-4 text-gray-400 animate-spin" />
              </div>
              <div className="flex-1">
                <div className="h-3 bg-gray-100 rounded w-24 mb-2" />
                <div className="h-4 bg-gray-100 rounded w-full" />
              </div>
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
});

ThinkingBlock.displayName = "ThinkingBlock";

export default ThinkingBlock;

