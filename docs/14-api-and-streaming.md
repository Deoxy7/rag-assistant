# 14 — API and streaming

**Status:** not yet written — filled in Phase 10.

What this doc will cover: FastAPI routes (/query with SSE streaming, /documents, /health), error handling, request/response models, and curl examples with real output.

## Planned sections

1. In one paragraph
2. Why it exists
3. Where it sits
4. The flow
5. The code
6. Data in / data out
7. Decisions & alternatives — Decision Cards #30, #31, #32
7a. Prerequisite concepts — HTTP request/response, chunked transfer encoding, Server-Sent Events, WebSockets, long polling, async/await and the event loop, thread pools for CPU-bound work, backpressure
7b. What if we used something else?
8. Failure modes
9. Try it yourself
10. Numbers — time to first token and total latency via curl
11. Interview talking points
12. Check yourself
13. New terms added to the glossary

Planned diagrams: SSE sequence: client ↔ API ↔ retriever ↔ LLM
