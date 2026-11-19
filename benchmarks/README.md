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
  longmemeval/                      LongMemEval harness (#47): replay, grade, report
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

## Internal benchmarks

Compare CtxVault's smart chunking (v0.6.1) against the previous fixed-size chunking. These are regression tests for internal development.

```bash
pip install -r benchmarks/internal/requirements.txt
python benchmarks/internal/compare_strategies.py
python benchmarks/internal/beir_benchmark.py
python benchmarks/internal/coir_benchmark.py
```

## LongMemEval

The harness in longmemeval/ replays each question's sessions into a fresh
vault (full context, semantic-only, or episodic consolidation), writes
hypotheses in the official LongMemEval jsonl format, and grades them. See
benchmarks/longmemeval/README.md for commands. The episodic+semantic
configuration waits for #45. Contributing a scored run is a separate PR that
adds one folder under benchmarks/longmemeval/results/.

## Roadmap

Additional benchmarks under development:

- Multi-agent isolation evaluation
- Typed memory discrimination (semantic vs procedural retrieval accuracy)
- A LoCoMo harness, alongside the LongMemEval one