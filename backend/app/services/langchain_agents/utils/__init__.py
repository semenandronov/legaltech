"""
Утилиты для LangGraph агентов.

Модули:
- reducers: Кастомные редьюсеры для агрегации состояния
- message_utils: Утилиты для работы с сообщениями
- streaming: Утилиты для streaming (разные режимы, токены)
- time_travel: Утилиты для time travel и debugging
- breakpoints: Утилиты для динамических breakpoints
"""

from app.services.langchain_agents.utils.reducers import (
    merge_dicts_reducer,
    append_unique_reducer,
    sort_by_confidence_reducer,
    append_errors_reducer,
    merge_citations_reducer,
    citations_state_reducer,
)

from app.services.langchain_agents.utils.message_utils import (
    filter_messages_by_count,
    trim_messages_by_tokens,
    summarize_old_messages,
    create_summary_message,
    get_remove_messages,
    merge_messages_with_summary,
    count_message_tokens_approx,
    should_trim_messages,
    MessageManager,
)

from app.services.langchain_agents.utils.streaming import (
    StreamMode,
    StreamEvent,
    stream_graph_with_mode,
    stream_tokens,
    stream_with_progress,
    format_sse_event,
    create_text_delta_event,
    create_finish_event,
)

from app.services.langchain_agents.utils.time_travel import (
    CheckpointInfo,
    StateSnapshot,
    get_state_history,
    get_state_at_checkpoint,
    replay_from_checkpoint,
    fork_checkpoint,
    compare_checkpoints,
    get_execution_path,
    rollback_to_checkpoint,
    TimeTravelManager,
)

from app.services.langchain_agents.utils.breakpoints import (
    BreakpointType,
    BreakpointConfig,
    NodeInterrupt,
    create_breakpoint_config,
    should_interrupt,
    low_confidence_condition,
    has_errors_condition,
    missing_context_condition,
    clarification_needed_condition,
    approval_required_condition,
    with_breakpoint,
    with_breakpoint_after,
    get_breakpoint_config_for_graph,
)

from app.services.langchain_agents.utils.state_editing import (
    StateUpdate,
    update_state,
    edit_message,
    remove_message,
    resume_with_updates,
    get_editable_state,
    StateEditor,
    create_human_feedback_update,
)

__all__ = [
    # Reducers
    "merge_dicts_reducer",
    "append_unique_reducer",
    "sort_by_confidence_reducer",
    "append_errors_reducer",
    "merge_citations_reducer",
    "citations_state_reducer",
    # Message utils
    "filter_messages_by_count",
    "trim_messages_by_tokens",
    "summarize_old_messages",
    "create_summary_message",
    "get_remove_messages",
    "merge_messages_with_summary",
    "count_message_tokens_approx",
    "should_trim_messages",
    "MessageManager",
    # Streaming
    "StreamMode",
    "StreamEvent",
    "stream_graph_with_mode",
    "stream_tokens",
    "stream_with_progress",
    "format_sse_event",
    "create_text_delta_event",
    "create_finish_event",
    # Time travel
    "CheckpointInfo",
    "StateSnapshot",
    "get_state_history",
    "get_state_at_checkpoint",
    "replay_from_checkpoint",
    "fork_checkpoint",
    "compare_checkpoints",
    "get_execution_path",
    "rollback_to_checkpoint",
    "TimeTravelManager",
    # Breakpoints
    "BreakpointType",
    "BreakpointConfig",
    "NodeInterrupt",
    "create_breakpoint_config",
    "should_interrupt",
    "low_confidence_condition",
    "has_errors_condition",
    "missing_context_condition",
    "clarification_needed_condition",
    "approval_required_condition",
    "with_breakpoint",
    "with_breakpoint_after",
    "get_breakpoint_config_for_graph",
    # State editing
    "StateUpdate",
    "update_state",
    "edit_message",
    "remove_message",
    "resume_with_updates",
    "get_editable_state",
    "StateEditor",
    "create_human_feedback_update",
]

