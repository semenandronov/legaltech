# Legal data security — production hardening

Shared responsibility: Yandex Cloud secures infrastructure; **we** secure
application code, observability egress, authorization, and contracts.

## Goals (legaltech)

1. Matter text must not leave the trust boundary via **provider logs** (Yandex AI).
2. Matter text must not leave via **third-party observability** (cloud Langfuse) by default.
3. Matter text must not appear in **application / access logs**.
4. Case/file APIs enforce **membership ACL** before any read of chat history or documents.
5. Transport: TLS verification on; HTTPS + security groups in ops.

## Layers (industry practice)

| Layer | Control |
| --- | --- |
| LLM provider | `YANDEX_DATA_LOGGING_ENABLED=false` → `x-data-logging-enabled: false` |
| Observability | `LANGFUSE_CAPTURE_CONTENT=false` (metadata-only) or Langfuse off |
| App logs | IDs + lengths only; no transcripts / cell values / prompt slices |
| Authz | `require_case_*` at route boundary **before** prep / retrieval |
| Abuse | HTTP rate-limit middleware |
| Ops | Security groups, TLS terminate, encrypted disks, DPA/NDA |

## Config (production)

```bash
ENVIRONMENT=production
YANDEX_DATA_LOGGING_ENABLED=false
LANGFUSE_ENABLED=false          # preferred for real matters
LANGFUSE_CAPTURE_CONTENT=false  # if Langfuse must stay on (self-host + DPA)
GIGACHAT_VERIFY_SSL=true
AGENT_DEBUG_FILE_LOG=false
```

## Explicit non-goals

This product **stores** case documents (disk/DB/vectors) so lawyers can reuse
them. Ephemeral RAM-only ZDR is a different product shape and is not the target
architecture here.
