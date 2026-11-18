"""Vector-only vs hybrid retrieval on a NanoBEIR dataset, same chunks, same model.

Runs a semantic vault over the dataset's corpus, then asks every query twice:
once with the vector leg alone, once with the keyword leg fused in (RRF). The
difference is the answer to "does exact-word retrieval earn its place".

Usage:
    python benchmarks/retrieval/hybrid_vs_vector.py
    python benchmarks/retrieval/hybrid_vs_vector.py --datasets nfcorpus scifact --limit 200
"""
import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_beir_dataset, make_vault, write_doc, compute_metrics, print_results  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from ctxvault.core.vaults.semantic import SemanticVault  # noqa: E402


def _run_dataset(name: str, limit: int | None) -> None:
    corpus, queries, qrels = load_beir_dataset(name)
    if limit:
        # Keep the queries whose answers are all inside the truncated corpus, so
        # the measurement is not dominated by documents that were never indexed.
        corpus_ids = set(list(corpus)[:limit])
        kept = {qid: text for qid, text in queries.items()
                if qrels.get(qid) and all(doc_id in corpus_ids for doc_id in qrels[qid])}
        queries = kept
        corpus = {doc_id: corpus[doc_id] for doc_id in corpus_ids}
        print(f"{name}: {len(corpus)} docs, {len(queries)} queries (limited)")

    tmp_dir = tempfile.mkdtemp(prefix=f"ctxvault-bench-{name}-")
    try:
        config = make_vault(tmp_dir, "bench")
        doc_ids = {}
        for doc_id, text in corpus.items():
            path = write_doc(config, doc_id, text)
            doc_ids[Path(path).stem] = doc_id

        vault = SemanticVault("bench", config)
        started = time.time()
        indexed, skipped = vault.index_files()
        print(f"{name}: indexed {len(indexed)} files in {time.time() - started:.1f}s, skipped {len(skipped)}")

        modes = (("vector-only", False), ("hybrid", True))
        raw_by_mode = {}
        for mode, hybrid in modes:
            raw_results = []
            started = time.time()
            for query_id, query_text in queries.items():
                t0 = time.perf_counter()
                result = vault.query(query_text, n_results=10, hybrid=hybrid)
                latency = (time.perf_counter() - t0) * 1000
                returned = []
                for match in result.results:
                    doc_id = doc_ids.get(Path(match.source).stem)
                    # A document can contribute several chunks; IR metrics are
                    # per document, so the first chunk is its rank.
                    if doc_id is not None and doc_id not in returned:
                        returned.append(doc_id)
                raw_results.append({"relevant": qrels[query_id], "returned": returned,
                                    "latency_ms": latency})
            raw_by_mode[mode] = raw_results
            print(f"{name} — {mode}: {time.time() - started:.1f}s total")

        all_results = {mode: {k: compute_metrics(raw_by_mode[mode], k) for k in (5, 10)}
                       for mode, _ in modes}
        print_results(name, all_results, [5, 10])
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", nargs="+", default=["nfcorpus", "scifact"],
                        choices=["nfcorpus", "scifact", "msmarco"])
    parser.add_argument("--limit", type=int, default=None, help="First N corpus documents only")
    args = parser.parse_args()
    for name in args.datasets:
        _run_dataset(name, args.limit)


if __name__ == "__main__":
    main()
