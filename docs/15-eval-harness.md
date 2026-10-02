# 15 — Evaluation harness

**Status:** not yet written — filled in Phase 11.

What this doc will cover: The golden question set and every metric derived from scratch with worked examples: recall@k, precision@k, MRR, nDCG@k, faithfulness, answer relevance, context precision, abstention.

## Planned sections

1. In one paragraph
2. Why it exists
3. Where it sits
4. The flow
5. The code
6. Data in / data out
7. Decisions & alternatives — Decision Cards #35, #36, #37, #38
7a. Prerequisite concepts — relevance judgments, recall@k, precision@k, MRR, DCG and nDCG, LLM-as-judge, judge bias and variance, abstention metrics, sample size and confidence intervals
7b. What if we used something else?
8. Failure modes
9. Try it yourself
10. Numbers — baseline metrics on the golden set, judge agreement with hand labels
11. Interview talking points
12. Check yourself
13. New terms added to the glossary

Planned diagrams: eval loop, metric decision tree, golden-set construction
