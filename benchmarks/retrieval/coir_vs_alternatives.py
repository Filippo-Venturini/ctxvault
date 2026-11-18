"""
CoIR Benchmark — CtxVault vs ChromaDB vs LangChain on code search datasets.

Compares three systems on CoIR subsets using identical corpora and queries.
All systems use the same embedding model (sentence-transformers) for fair comparison.
Runs entirely locally — no API keys needed.

Usage:
    python benchmarks/retrieval/coir_vs_alternatives.py
    python benchmarks/retrieval/coir_vs_alternatives.py --datasets cosqa stackoverflow-qa --top-k 5 10 --max-corpus 5000
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import (
    make_vault,
    write_doc,
    compute_metrics,
    print_results,
)

# Prevent benchmarks/evaluate.py from shadowing the `evaluate` package
# required by coir's internal imports.
_benchmarks_dir = str(Path(__file__).parent.parent)
if _benchmarks_dir in sys.path:
    sys.path.remove(_benchmarks_dir)


# ---------------------------------------------------------------------------
# Dataset loading — CoIR
# ---------------------------------------------------------------------------

def load_coir_dataset(name: str, max_corpus: int | None = None) -> tuple[dict, dict, dict]:
    """Load corpus, queries, and qrels from a CoIR dataset.

    Returns:
        corpus: {doc_id: text}
        queries: {query_id: text}
        qrels: {query_id: set(doc_ids)}
    """
    import coir

    raw_corpus, raw_queries, raw_qrels = coir.load_data_from_hf(name)

    corpus = {}
    for cid, doc in raw_corpus.items():
        text = doc["text"]
        if doc.get("title"):
            text = doc["title"] + "\n" + text
        corpus[cid] = text

    queries = dict(raw_queries)

    qrels = {}
    for qid, rels in raw_qrels.items():
        positive = {cid for cid, score in rels.items() if score > 0}
        if positive:
            qrels[qid] = positive

    queries = {qid: text for qid, text in queries.items() if qid in qrels}

    if max_corpus and len(corpus) > max_corpus:
        relevant_ids = set()
        for rels in qrels.values():
            relevant_ids.update(rels)

        keep_ids = set(relevant_ids)
        remaining = [cid for cid in corpus if cid not in keep_ids]
        import random
        random.seed(42)
        sample_size = max_corpus - len(keep_ids)
        if sample_size > 0:
            keep_ids.update(random.sample(remaining, min(sample_size, len(remaining))))

        corpus = {cid: text for cid, text in corpus.items() if cid in keep_ids}

    return corpus, queries, qrels


# ---------------------------------------------------------------------------
# Shared: embedding model
# ---------------------------------------------------------------------------

_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _embed(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    return model.encode(texts, show_progress_bar=False).tolist()


# ---------------------------------------------------------------------------
# Shared: chunking for baselines
# ---------------------------------------------------------------------------

def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 100) -> list[str]:
    words = text.split()
    if not words:
        return [text]
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    step = max(chunk_size - overlap, 1)
    for i in range(0, len(words), step):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk.strip())
    return chunks


# ---------------------------------------------------------------------------
# Strategy 1: CtxVault (full pipeline)
# ---------------------------------------------------------------------------

def _index_ctxvault(file_path: str, config: dict):
    from ctxvault.core.indexer import index_file
    index_file(file_path=file_path, config=config)


def _query_ctxvault(query_txt: str, config: dict, n_results: int = 20) -> dict:
    from ctxvault.core.querying import query
    return query(query_txt=query_txt, config=config, n_results=n_results)


def _query_ctxvault_hybrid(query_txt: str, config: dict, n_results: int = 20) -> dict:
    """Same vault and index, keyword leg included: code identifiers are exactly
    what a vector-only retriever misses."""
    from ctxvault.core.vaults.semantic import SemanticVault
    result = SemanticVault("bench", config).query(text=query_txt, n_results=n_results, hybrid=True)
    return {"metadatas": [[{"source": chunk.source} for chunk in result.results]]}


# ---------------------------------------------------------------------------
# Strategy 2: ChromaDB raw
# ---------------------------------------------------------------------------

_chroma_clients = {}

def _get_chroma_collection(config: dict):
    import chromadb

    db_path = config["db_path"]
    if db_path not in _chroma_clients:
        client = chromadb.PersistentClient(path=db_path)
        collection = client.get_or_create_collection(
            name="benchmark",
            metadata={"hnsw:space": "cosine"},
        )
        _chroma_clients[db_path] = (client, collection)
    return _chroma_clients[db_path][1]


def _index_chromadb_raw(file_path: str, config: dict):
    collection = _get_chroma_collection(config)

    text = Path(file_path).read_text(encoding="utf-8")
    doc_id = Path(file_path).stem
    chunks = _chunk_text(text)
    embeddings = _embed(chunks)

    ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"source": file_path, "doc_id": doc_id, "chunk_index": i} for i in range(len(chunks))]

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )


def _query_chromadb_raw(query_txt: str, config: dict, n_results: int = 20) -> dict:
    collection = _get_chroma_collection(config)
    query_embedding = _embed([query_txt])

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=n_results,
    )

    return {
        "documents": results["documents"],
        "metadatas": results["metadatas"],
        "distances": results["distances"],
    }


# ---------------------------------------------------------------------------
# Strategy 3: LangChain retriever
# ---------------------------------------------------------------------------

_langchain_stores = {}

def _get_langchain_store(config: dict):
    from langchain_community.vectorstores import Chroma
    from langchain_community.embeddings import SentenceTransformerEmbeddings

    db_path = config["db_path"]
    if db_path not in _langchain_stores:
        embedding_fn = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")
        store = Chroma(
            persist_directory=db_path,
            embedding_function=embedding_fn,
            collection_name="benchmark",
        )
        _langchain_stores[db_path] = store
    return _langchain_stores[db_path]


def _index_langchain(file_path: str, config: dict):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    store = _get_langchain_store(config)

    text = Path(file_path).read_text(encoding="utf-8")
    doc_id = Path(file_path).stem

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000,
        chunk_overlap=200,
        length_function=len,
    )
    chunks = splitter.split_text(text)

    metadatas = [{"source": file_path, "doc_id": doc_id, "chunk_index": i} for i in range(len(chunks))]
    ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]

    store.add_texts(texts=chunks, metadatas=metadatas, ids=ids)


def _query_langchain(query_txt: str, config: dict, n_results: int = 20) -> dict:
    store = _get_langchain_store(config)
    docs = store.similarity_search(query_txt, k=n_results)

    metadatas = [doc.metadata for doc in docs]
    documents = [doc.page_content for doc in docs]

    return {
        "documents": [documents],
        "metadatas": [metadatas],
        "distances": [[0.0] * len(documents)],
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_single_strategy(
    strategy_name: str,
    corpus: dict,
    queries: dict,
    qrels: dict,
    index_fn,
    query_fn,
    top_k_list: list[int],
) -> dict[int, dict]:

    _chroma_clients.clear()
    _langchain_stores.clear()
    try:
        from ctxvault.storage.chroma_store import _clients, _collections
        _clients.clear()
        _collections.clear()
    except ImportError:
        pass
    try:
        from ctxvault.storage.bm25_store import _indexes
        _indexes.clear()
    except ImportError:
        pass

    tmp_dir = tempfile.mkdtemp(prefix=f"bench_{strategy_name}_")
    config = make_vault(tmp_dir)

    stem_to_cid = {}
    for cid in corpus:
        safe_id = cid.replace("/", "_").replace("\\", "_")
        stem_to_cid[safe_id] = cid

    try:
        for i, (cid, text) in enumerate(corpus.items()):
            fpath = write_doc(config, cid, text)
            index_fn(fpath, config)
            if (i + 1) % 1000 == 0:
                print(f"    indexed {i + 1}/{len(corpus)}", flush=True)

        max_k = max(top_k_list)
        over_fetch = max_k * 4

        raw_results = []
        for qi, (qid, qtext) in enumerate(queries.items()):
            start = time.perf_counter()
            raw = query_fn(qtext, config, n_results=over_fetch)
            latency_ms = (time.perf_counter() - start) * 1000

            returned_cids = []
            seen = set()
            for meta in raw["metadatas"][0]:
                stem = Path(meta.get("source", "")).stem
                cid = stem_to_cid.get(stem)
                if cid and cid not in seen:
                    seen.add(cid)
                    returned_cids.append(cid)

            raw_results.append({
                "qid": qid,
                "relevant": qrels.get(qid, set()),
                "returned": returned_cids,
                "latency_ms": latency_ms,
            })

            if (qi + 1) % 100 == 0:
                print(f"    queried {qi + 1}/{len(queries)}", flush=True)

        results_by_k = {}
        for k in top_k_list:
            results_by_k[k] = compute_metrics(raw_results, k)
        return results_by_k

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _strategy_key(label: str) -> str:
    if label.startswith("CtxVault"):
        return "ctxvault_hybrid" if "hybrid" in label else "ctxvault"
    return label.split("(")[0].strip().lower().replace(" ", "_")


def main():
    parser = argparse.ArgumentParser(
        description="CoIR benchmark: CtxVault vs ChromaDB vs LangChain"
    )
    parser.add_argument(
        "--datasets", nargs="+",
        default=["cosqa", "stackoverflow-qa"],
    )
    parser.add_argument(
        "--top-k", nargs="+", type=int, default=[5, 10],
    )
    parser.add_argument(
        "--max-corpus", type=int, default=5000,
        help="Max corpus size per dataset (subsample if larger)",
    )
    parser.add_argument(
        "--strategies", nargs="+",
        choices=["chromadb", "langchain", "ctxvault", "ctxvault_hybrid"],
        help="Which systems to run; default all. The two CtxVault rows share an "
             "indexing pipeline and differ only in the query path.",
    )
    args = parser.parse_args()

    print("Warming up embedding model...", flush=True)
    _get_model()
    from ctxvault.core.embedding import embed_list
    embed_list(chunks=["warmup"])

    strategies = [
        ("ChromaDB (raw)",       _index_chromadb_raw, _query_chromadb_raw),
        ("LangChain retriever",  _index_langchain,    _query_langchain),
        ("CtxVault (full)",      _index_ctxvault,     _query_ctxvault),
        ("CtxVault (hybrid)",    _index_ctxvault,     _query_ctxvault_hybrid),
    ]
    if args.strategies:
        wanted = set(args.strategies)
        strategies = [s for s in strategies if _strategy_key(s[0]) in wanted]

    for ds_name in args.datasets:
        print(f"\n{'=' * 70}")
        print(f"  Dataset: {ds_name}")
        print(f"{'=' * 70}")

        print(f"  Loading {ds_name}...", flush=True)
        corpus, queries, qrels = load_coir_dataset(ds_name, max_corpus=args.max_corpus)
        print(f"  Corpus: {len(corpus)} docs | Queries: {len(queries)}")

        all_results = {}
        for label, idx_fn, qry_fn in strategies:
            tag = label.split("(")[0].strip()
            print(f"\n  [{tag}] Indexing + querying...", flush=True)
            by_k = run_single_strategy(
                f"{ds_name}_{tag.lower().replace(' ', '_')}",
                corpus, queries, qrels,
                index_fn=idx_fn, query_fn=qry_fn,
                top_k_list=args.top_k,
            )
            all_results[label] = by_k
            print(f"  [{tag}] Done.", flush=True)

        print_results(ds_name, all_results, args.top_k)

    print()


if __name__ == "__main__":
    main()