"""
BEIR Benchmark — CtxVault vs ChromaDB vs LangChain on standard IR datasets.

Compares three systems on NanoBEIR subsets using identical corpora and queries.
All systems use the same embedding model (sentence-transformers) for fair comparison.
Runs entirely locally — no API keys needed.

Usage:
    python benchmarks/retrieval/beir_vs_alternatives.py
    python benchmarks/retrieval/beir_vs_alternatives.py --datasets nfcorpus scifact msmarco --top-k 5 10
"""

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import (
    BEIR_DATASETS,
    load_beir_dataset,
    make_vault,
    write_doc,
    compute_metrics,
    print_results,
)


# ---------------------------------------------------------------------------
# Shared: embedding model
# ---------------------------------------------------------------------------

_model = None

def _get_model():
    """Lazy-load the sentence-transformers model (same one CtxVault uses)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _embed(texts: list[str]) -> list[list[float]]:
    """Embed texts using the shared model."""
    model = _get_model()
    return model.encode(texts, show_progress_bar=False).tolist()


# ---------------------------------------------------------------------------
# Shared: chunking
# ---------------------------------------------------------------------------

def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 100) -> list[str]:
    """Simple word-based chunking used for ChromaDB and LangChain baselines.

    Uses the same defaults as CtxVault's current chunking to isolate
    the comparison to the retrieval system, not the chunking strategy.
    """
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
    """Index using CtxVault's full pipeline (smart chunking + hybrid search)."""
    from ctxvault.core.indexer import index_file
    index_file(file_path=file_path, config=config)


def _query_ctxvault(query_txt: str, config: dict, n_results: int = 20) -> dict:
    """Query using CtxVault's full pipeline."""
    from ctxvault.core.querying import query
    return query(query_txt=query_txt, config=config, n_results=n_results)


def _query_ctxvault_hybrid(query_txt: str, config: dict, n_results: int = 20) -> dict:
    """The same vault and index, ranking by the keyword leg as well; only the
    query path differs, so the comparison isolates fusion, not indexing."""
    from ctxvault.core.vaults.semantic import SemanticVault
    result = SemanticVault("bench", config).query(text=query_txt, n_results=n_results, hybrid=True)
    return {"metadatas": [[{"source": chunk.source} for chunk in result.results]]}


# ---------------------------------------------------------------------------
# Strategy 2: ChromaDB raw (direct usage, no CtxVault)
# ---------------------------------------------------------------------------

_chroma_clients = {}

def _get_chroma_collection(config: dict):
    """Get or create a ChromaDB collection for direct usage."""
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
    """Index directly into ChromaDB: read file, chunk, embed, store."""
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
    """Query ChromaDB directly with cosine similarity."""
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
    """Get or create a LangChain Chroma vectorstore."""
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
    """Index using LangChain's text splitter + Chroma vectorstore."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    store = _get_langchain_store(config)

    text = Path(file_path).read_text(encoding="utf-8")
    doc_id = Path(file_path).stem

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000,       # characters, not words — LangChain default
        chunk_overlap=200,
        length_function=len,
    )
    chunks = splitter.split_text(text)

    metadatas = [{"source": file_path, "doc_id": doc_id, "chunk_index": i} for i in range(len(chunks))]
    ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]

    store.add_texts(texts=chunks, metadatas=metadatas, ids=ids)


def _query_langchain(query_txt: str, config: dict, n_results: int = 20) -> dict:
    """Query using LangChain's similarity search."""
    store = _get_langchain_store(config)
    docs = store.similarity_search(query_txt, k=n_results)

    # Convert to the same format as CtxVault/ChromaDB for unified metric computation
    metadatas = [doc.metadata for doc in docs]
    documents = [doc.page_content for doc in docs]

    return {
        "documents": [documents],
        "metadatas": [metadatas],
        "distances": [[0.0] * len(documents)],  # LangChain doesn't return distances by default
    }


# ---------------------------------------------------------------------------
# Runner (wraps the generic runner with per-strategy cache clearing)
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
    """Run a single strategy benchmark with proper cache isolation."""

    # Clear all caches
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

    # Build reverse lookup: safe filename stem -> corpus_id
    stem_to_cid = {}
    for cid in corpus:
        safe_id = cid.replace("/", "_").replace("\\", "_")
        stem_to_cid[safe_id] = cid

    try:
        # Index
        for i, (cid, text) in enumerate(corpus.items()):
            fpath = write_doc(config, cid, text)
            index_fn(fpath, config)
            if (i + 1) % 500 == 0:
                print(f"    indexed {i + 1}/{len(corpus)}", flush=True)

        max_k = max(top_k_list)
        over_fetch = max_k * 4

        # Query
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
        description="BEIR benchmark: CtxVault vs ChromaDB vs LangChain"
    )
    parser.add_argument(
        "--datasets", nargs="+",
        choices=list(BEIR_DATASETS.keys()),
        default=["nfcorpus", "scifact"],
    )
    parser.add_argument(
        "--top-k", nargs="+", type=int, default=[5, 10],
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
    # Also warm up CtxVault's internal model
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

        print(f"  Loading {BEIR_DATASETS[ds_name]}...", flush=True)
        corpus, queries, qrels = load_beir_dataset(ds_name)
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