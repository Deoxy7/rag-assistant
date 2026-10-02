# 11 — Hybrid search and RRF

**Status:** not yet written — filled in Phase 7.

What this doc will cover: Fusing two ranked lists with Reciprocal Rank Fusion, derived by hand on a toy example; the k constant; switching between vector-only, keyword-only and hybrid.

## Planned sections

1. In one paragraph
2. Why it exists
3. Where it sits
4. The flow
5. The code
6. Data in / data out
7. Decisions & alternatives — Decision Cards #20, #22, #23
7a. Prerequisite concepts — rank vs score, why raw scores from different systems can't be compared, score normalisation, the RRF formula term by term, the k constant
7b. What if we used something else?
8. Failure modes
9. Try it yourself
10. Numbers — hybrid vs each single mode on the golden set
11. Interview talking points
12. Check yourself
13. New terms added to the glossary

Planned diagrams: two lists → fusion → one ranking, worked example with numbers
