> **About this sample.** It was generated in the build environment, where neither Ollama nor the
> sentence-transformers weights were available. It used `scripts/dev_stubs.py` (a rule-based stand-in,
> **not a language model**) and the lexical `hash` embedder. Retrieval and tool-selection numbers come from
> the real pipeline (Qdrant, chunking, LangGraph agent, validators); answer-quality numbers only show the
> report format. Re-run it with a real model to get meaningful results:
>
> ```bash
> cd backend && python -m app.cli eval --out ../docs/evaluation-report.md
> ```

# Evaluation report: default

- Run at: 2026-10-17T15:25:37.852068+00:00
- Chat model: `fake-llm`; embedding model: `hash-384`
- Retrieval: top_k=5, score_threshold=0.05
- Duration: 6009 ms

## Summary

| Metric | Value |
| --- | --- |
| Retrieval hit rate | 0.88 |
| Recall@k | 0.88 |
| Citation validity | 1.00 |
| Answer completeness (estimate) | 0.19 |
| Groundedness (lexical estimate) | 0.60 |
| Tool-selection success rate | 1.00 |
| Task completion rate | 0.17 |
| Correct abstention on unanswerable questions | 0.00 |
| Latency p50 (ms) | 525 |
| Latency p95 (ms) | 585 |

## Items

| Id | Mode | Status | Tools executed | Hit | Recall@k | Citations | Completeness (est.) | Tool choice | Latency ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rag-booking | document_rag | success | document_retrieval | yes | 1.00 | 1.00 | 0.00 | n/a | 553 |
| rag-exclusions | document_rag | success | document_retrieval | yes | 1.00 | 1.00 | 0.33 | n/a | 524 |
| rag-hotel | document_rag | success | document_retrieval | yes | 1.00 | 1.00 | 0.00 | n/a | 525 |
| rag-mfa | document_rag | success | document_retrieval | yes | 1.00 | 1.00 | 0.50 | n/a | 527 |
| rag-incident | document_rag | success | document_retrieval | yes | 1.00 | 1.00 | 0.00 | n/a | 522 |
| rag-returns | document_rag | success | document_retrieval | yes | 1.00 | 1.00 | 0.00 | n/a | 513 |
| rag-unanswerable | document_rag | success | document_retrieval | n/a | n/a | 1.00 | 0.50 | n/a | 520 |
| agent-calculator | agent | success | calculator | n/a | n/a | n/a | 1.00 | yes | 169 |
| agent-sql | agent | success | sql_query | n/a | n/a | 1.00 | 0.00 | yes | 629 |
| agent-docs | agent | success | document_retrieval | no | 0.00 | 1.00 | 0.00 | yes | 585 |
| agent-disabled-tool | agent | success | - | n/a | n/a | n/a | 0.00 | yes | 280 |
| agent-docs-and-math | agent | success | document_retrieval | yes | 1.00 | 1.00 | 0.00 | yes | 581 |

## Notes

- completeness_estimate and groundedness_estimate are lexical heuristics, not judgments of correctness.
- recall_at_k counts chunks containing the ground-truth phrase as relevant.
