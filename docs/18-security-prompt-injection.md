# 18 — Security and prompt injection

**Status:** not yet written — filled in Phase 14.

What this doc will cover: The OWASP Top 10 for LLM applications as it applies here, prompt-injection tests through ingested documents, input validation, output constraints, and SQL-injection checks; an attack that worked before the fix and fails after.

## Planned sections

1. In one paragraph
2. Why it exists
3. Where it sits
4. The flow
5. The code
6. Data in / data out
7. Decisions & alternatives — Decision Cards #40, #41
7a. Prerequisite concepts — direct vs indirect prompt injection, trust boundaries, SQL injection and parameter binding, input validation, row-level security vs metadata filters
7b. What if we used something else?
8. Failure modes
9. Try it yourself
10. Numbers — attack success rate before vs after mitigations
11. Interview talking points
12. Check yourself
13. New terms added to the glossary

Planned diagrams: threat model, injection path + mitigations
