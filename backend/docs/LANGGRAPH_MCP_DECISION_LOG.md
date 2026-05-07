# LangGraph MCP Decision Log

## Purpose
Capture implementation decisions for the internal assistant based on LangGraph/DeepAgents documentation accessed through MCP.

## MCP Access Notes
- Server: `user-Docs by LangChain`
- Tools used:
  - `search_docs_by_lang_chain`
  - `query_docs_filesystem_docs_by_lang_chain`
- Verified topics:
  - LangGraph overview (durable execution, streaming, human-in-the-loop)
  - DeepAgents human-in-the-loop
  - Workflows vs agents patterns

## Documentation Anchors
- LangGraph overview:
  - https://docs.langchain.com/oss/python/langgraph/overview
- DeepAgents human-in-the-loop:
  - https://docs.langchain.com/oss/python/deepagents/human-in-the-loop
- Workflows and agents:
  - https://docs.langchain.com/oss/python/langgraph/workflows-agents

## Decisions
1. **Keep graph as orchestration backbone**
   - Reason: LangGraph is designed for durable, stateful orchestration and runtime control.
2. **Use deterministic fast/entity path before agentic reasoning**
   - Reason: Workflows are preferable for predictable factual paths; agentic loops reserved for complex ambiguity.
3. **Preserve HITL-ready contracts in deep path**
   - Reason: DeepAgents docs emphasize interrupt/checkpointer patterns for safe tool operations.
4. **Enforce budget and coverage contracts in orchestration layer**
   - Reason: runtime guarantees should be explicit and observable at graph/orchestrator level, not hidden in prompts.

## Backlog from docs alignment
- Add route-level confidence and fallback reasons to all request traces.
- Expand deep runtime budget tracking (tool calls, llm calls, wall-time) with strict status events.
- Keep deep canary rollout gated by eval metrics before 100% cutover.
