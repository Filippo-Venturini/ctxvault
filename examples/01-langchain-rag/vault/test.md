# RAG Evaluation Document

This markdown document is designed to test **Retrieval-Augmented Generation (RAG)** systems. It includes structured data, unstructured text, tables, timelines, edge cases, and deliberately confusing elements (near-duplicates, contradictions, and long-range references).

---

## 1. Overview

**Project Codename:** ORION-LENS
**Domain:** Applied AI Systems
**Primary Use Case:** Internal document retrieval and question answering
**Last Updated:** 2024-11-03

ORION-LENS is a fictional AI platform designed for multimodal document analysis. It was first proposed in 2021 and reached version 3.2 in late 2024.

---

## 2. Key Facts (High-Precision Retrieval Targets)

* ORION-LENS was **initially proposed in 2021**.
* The **lead architect** is **Dr. Elena Markovic**.
* Version **3.0** introduced *context-aware retrieval*.
* Version **3.1** was **skipped** due to internal restructuring.
* Version **3.2** is the **current stable release**.

> ⚠️ Note: Some internal memos incorrectly list version 3.1 as a public beta. This is false.

---

## 3. Architecture Description (Unstructured Text)

ORION-LENS uses a hybrid retrieval pipeline combining dense vector search with symbolic filters. Documents are chunked using a dynamic windowing strategy that adapts to semantic boundaries rather than fixed token counts.

The generation layer is model-agnostic and supports multiple large language models via an abstraction interface. In early experiments, this reduced hallucinations by approximately 18%, although later audits revised this figure downward.

---

## 4. Performance Metrics (Table)

| Version | Release Date | Avg. Latency (ms) | Hallucination Rate |
| ------- | ------------ | ----------------- | ------------------ |
| 2.5     | 2022-08-14   | 420               | 12.4%              |
| 3.0     | 2023-05-02   | 390               | 9.1%               |
| 3.2     | 2024-10-19   | 360               | 9.8%               |

**Important:** Despite common assumptions, version 3.2 does **not** have the lowest hallucination rate.

---

## 5. Timeline of Events

* **2021 Q2:** Initial proposal drafted
* **2022 Q3:** Version 2.5 released
* **2023 Q2:** Version 3.0 released with context-aware retrieval
* **2024 Q1:** Internal audit identifies metric reporting errors
* **2024 Q4:** Version 3.2 released

---

## 6. Conflicting Statements (For Disambiguation Testing)

* Statement A: *“ORION-LENS reduced hallucinations by 18% after introducing context-aware retrieval.”*
* Statement B: *“Later audits showed the actual reduction was closer to 11%.”*

**Resolution:** Statement B reflects the corrected figure and supersedes Statement A.

---

## 7. Long-Range Reference Test

As mentioned briefly in **Section 2**, version 3.1 was skipped. This decision is explained in detail here:

During late 2023, the engineering team underwent a major reorganization. To avoid releasing an unstable build, the version number 3.1 was intentionally omitted from public releases.

---

## 8. Code Snippet (Non-Natural Language Content)

```python
class OrionLensRetriever:
    def __init__(self, embedding_model):
        self.model = embedding_model

    def retrieve(self, query, k=5):
        return self.model.search(query, top_k=k)
```

This snippet is illustrative only and not production code.

---

## 9. Frequently Asked Questions

**Q: Is ORION-LENS open source?**
A: No. It is an internal platform.

**Q: Who is responsible for metric validation?**
A: The Applied Research Audit Group (ARAG).

**Q: What is the current stable version?**
A: Version 3.2.

---

## 10. Embedded Retrieval Traps

* The name **Orion Lens** (without hyphen) appears in some legacy documents — this refers to the same system.
* Some charts label version 3.2 as *"v3.20"* — this is a formatting error.
* Do not confuse **hallucination rate** with **error rate**; they are measured differently.

---

## 11. Summary

This document is intentionally designed to test:

* Precise fact retrieval
* Conflict resolution
* Table understanding
* Long-context reasoning
* Resistance to misleading or outdated information
