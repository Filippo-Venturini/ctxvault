# Benchmarks

Evaluation infrastructure for CtxVault. Work in progress.

## Structure

```
benchmarks/
  utils.py                          shared helpers (vault setup, metrics, dataset loaders)
  internal/
    compare_strategies.py           A/B comparison of chunking strategies (old vs new)
    beir_benchmark.py               BEIR evaluation of chunking strategies
    coir_benchmark.py               CoIR evaluation of chunking strategies
  retrieval/
    beir_vs_alternatives.py         CtxVault vs ChromaDB vs LangChain on BEIR
    coir_vs_alternatives.py         CtxVault vs ChromaDB vs LangChain on CoIR
```

`internal/` benchmarks compare CtxVault's own chunking strategies against each other.
`retrieval/` benchmarks compare CtxVault against alternative retrieval systems on the same datasets, same embedding model, same queries.

## Retrieval benchmarks

Compare CtxVault's full pipeline against ChromaDB (raw) and LangChain retriever on standard IR datasets. All systems use the same embedding model (all-MiniLM-L6-v2) for fair comparison.

### Setup

```bash
pip install -r benchmarks/retrieval/requirements.txt
```

### Run

```bash
python benchmarks/retrieval/beir_vs_alternatives.py
python benchmarks/retrieval/coir_vs_alternatives.py
```

Both scripts include a `CtxVault (hybrid)` row: the same chunks and index as
`CtxVault (full)`, with the keyword leg fused in at query time. To compare only
the two CtxVault rows (one indexing pass each, same pipeline), pass:

```bash
python benchmarks/retrieval/beir_vs_alternatives.py --datasets nfcorpus scifact \
    --strategies ctxvault ctxvault_hybrid
python benchmarks/retrieval/coir_vs_alternatives.py --datasets cosqa stackoverflow-qa \
    --strategies ctxvault ctxvault_hybrid
```

### Results

Tested on BEIR (NFCorpus, SciFact) and CoIR (CoSQA, StackOverflow-QA). CtxVault introduces no retrieval overhead compared to raw ChromaDB or LangChain.

**BEIR**

| Dataset  | Strategy            | P@5   | R@5   | MRR    | nDCG@5 |
|----------|---------------------|-------|-------|--------|--------|
| NFCorpus | ChromaDB (raw)      | 33.2% | 9.2%  | 0.4857 | 0.3619 |
|          | LangChain retriever | 32.4% | 8.3%  | 0.4833 | 0.3562 |
|          | CtxVault (full)     | 33.2% | 9.2%  | 0.4857 | 0.3619 |
| SciFact  | ChromaDB (raw)      | 18.0% | 80.0% | 0.6897 | 0.7157 |
|          | LangChain retriever | 18.0% | 80.0% | 0.7013 | 0.7245 |
|          | CtxVault (full)     | 18.0% | 80.0% | 0.6897 | 0.7157 |

**CoIR**

| Dataset          | Strategy            | P@5   | R@5   | MRR    | nDCG@5 |
|------------------|---------------------|-------|-------|--------|--------|
| CoSQA            | ChromaDB (raw)      | 12.5% | 62.6% | 0.3636 | 0.4290 |
|                  | LangChain retriever | 12.5% | 62.6% | 0.3636 | 0.4290 |
|                  | CtxVault (full)     | 12.5% | 62.6% | 0.3636 | 0.4290 |
| StackOverflow-QA | ChromaDB (raw)      | 18.9% | 94.3% | 0.8850 | 0.8998 |
|                  | LangChain retriever | 18.8% | 94.1% | 0.8845 | 0.8989 |
|                  | CtxVault (full)     | 18.9% | 94.4% | 0.8881 | 0.9023 |

CtxVault matches or marginally exceeds ChromaDB and LangChain across all datasets and metrics. The vault abstraction adds no measurable retrieval overhead.

## Hybrid retrieval

The two scripts above add a `CtxVault (hybrid)` row: same chunks and index as
`CtxVault (full)`, with the FTS5 keyword leg fused by reciprocal rank fusion at
query time. Run only the two CtxVault rows (one indexing pass each):

```bash
python benchmarks/retrieval/beir_vs_alternatives.py --datasets nfcorpus scifact \
    --strategies ctxvault ctxvault_hybrid
python benchmarks/retrieval/coir_vs_alternatives.py --datasets cosqa stackoverflow-qa \
    --strategies ctxvault ctxvault_hybrid
```

**BEIR** (document-level metrics, same `all-MiniLM-L6-v2`):

| Dataset  | Mode        | P@5   | R@5   | MRR    | nDCG@5 | R@10  | p50    |
|----------|-------------|-------|-------|--------|--------|-------|--------|
| NFCorpus | vector-only | 32.4% | 9.7% | 0.5100 | 0.3669 | 12.9% | 15.1ms |
|          | hybrid      | 34.4% | 12.0% | 0.5333 | 0.3943 | 15.4% | 55.5ms |
| SciFact  | vector-only | 18.0% | 80.0% | 0.6990 | 0.7214 | 85.0% | 12.6ms |
|          | hybrid      | 18.0% | 80.0% | 0.6990 | 0.7214 | 85.0% | 50.9ms |

**CoIR** (5 000 documents per dataset):

| Dataset          | Mode        | P@5   | R@5   | MRR    | nDCG@5 | R@10  | p50    |
|------------------|-------------|-------|-------|--------|--------|-------|--------|
| CoSQA            | vector-only | 13.3% | 66.4% | 0.4562 | 0.5079 | 78.4% | 10.8ms |
|                  | hybrid      | 13.3% | 66.4% | 0.4560 | 0.5078 | 78.4% | 43.4ms |
| StackOverflow-QA | vector-only | 19.0% | 94.9% | 0.9023 | 0.9142 | 96.6% | 26.6ms |
|                  | hybrid      | 19.0% | 95.0% | 0.9026 | 0.9145 | 96.7% | 68.8ms |

The keyword leg requires every query term (`AND`), not any one (`OR`). With
`OR`, CoSQA and StackOverflow-QA lost 9–10 points of R@5: a prose question
shares one common word with thousands of chunks and those hits displaced the
vector leader. With `AND` the leg is silent unless the whole query is present,
so CoIR is neutral and the NFCorpus gain survives; single-token queries such as
`ERR_4021` behave exactly as before.

The index is built during `reindex` or the first hybrid query; 5 000 chunks cost
1.85 s to write, 3.4 ms to search and 1.5 MB on disk.

## Internal benchmarks

Compare CtxVault's smart chunking (v0.6.1) against the previous fixed-size chunking. These are regression tests for internal development.

```bash
pip install -r benchmarks/internal/requirements.txt
python benchmarks/internal/compare_strategies.py
python benchmarks/internal/beir_benchmark.py
python benchmarks/internal/coir_benchmark.py
```

## Roadmap

Additional benchmarks under development:

- Multi-agent isolation evaluation
- Typed memory discrimination (semantic vs procedural retrieval accuracy)
- Cross-session persistence with LongMemEval / LoCoMo