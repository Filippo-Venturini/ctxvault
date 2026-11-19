"""Finding prune candidates in a semantic vault. Reads only; never writes.

Documents are the unit: a semantic vault is file-backed, so a chunk removed
from the index alone comes back on the next reindex of its file. Chunk-level
findings are evidence for a decision about a document.
"""

import hashlib
import math
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ctxvault.core.embedding import DEFAULT_EMBEDDING_MODEL
from ctxvault.models.pruning import Candidate, PruneAction, PruneMode, PrunePolicy, PruneReport, ReasonSpec
from ctxvault.storage import chroma_store
from ctxvault.utils.metadata_builder import BUILT_IN_METADATA_KEYS
from ctxvault.utils.text_extraction import extract_text

DUPLICATE = "duplicate"                  # the same document under two paths
DUPLICATE_PARTIAL = "duplicate_partial"  # two documents that share passages
STALE = "stale"                          # a file not modified in a long time

SEMANTIC_REASONS: dict[str, ReasonSpec] = {
    DUPLICATE: ReasonSpec(default_mode=PruneMode.AUTO, auto_eligible=True),
    DUPLICATE_PARTIAL: ReasonSpec(default_mode=PruneMode.REPORT, auto_eligible=False),
    STALE: ReasonSpec(default_mode=PruneMode.REPORT, auto_eligible=True),
}

# Cosine similarity above which two chunks of different documents count as
# the same passage, per embedding model. A number tuned for one model means
# something else for another, so a model with no entry here gets no partial
# overlap check unless the vault sets a threshold of its own.
KNOWN_THRESHOLDS = {
    DEFAULT_EMBEDDING_MODEL: 0.95,
    DEFAULT_EMBEDDING_MODEL.split("/")[-1]: 0.95,
}
DEFAULT_STALE_DAYS = 180

# A file's mtime and an agent's write timestamp come from different clocks' roundings.
_SLACK = timedelta(seconds=1)
_NEIGHBOURS = 3

@dataclass
class _Doc:
    doc_id: str
    source: str
    metadata: dict
    modified: datetime | None
    chunks: list[tuple[int, str, list[float] | None]] = field(default_factory=list)

    @property
    def exists(self) -> bool:
        return self.modified is not None

def _instant(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # Python 3.10's fromisoformat does not accept a trailing "Z".
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

def _vector(value) -> list[float] | None:
    if value is None:
        return None
    vector = [float(x) for x in value]
    return vector or None

def _rows(value) -> list:
    """A query result field as a list, whether Chroma gave a list, an array or nothing."""
    return [] if value is None else list(value)

def _cosine(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return None
    return sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)

def agent_written(doc: _Doc) -> bool:
    """Written by an agent and not edited since. Needs both `generated_by` and
    `timestamp`: a document with only the first (the Python client takes free
    metadata) counts as human-written. Copying a vault resets mtimes, which
    makes every document human-written: nothing is auto-pruned, the safe way
    to be wrong."""
    written_at = _instant(doc.metadata.get("timestamp"))
    if not doc.metadata.get("generated_by") or written_at is None or doc.modified is None:
        return False
    return doc.modified <= written_at + _SLACK

def text_hash(path: str) -> str:
    """The document's extracted text, normalised (Unicode NFC, whitespace
    collapsed), hashed. Equal hashes are the same document whatever the
    vault's model or chunking."""
    text, _ = extract_text(path)
    normalised = " ".join(unicodedata.normalize("NFC", text).split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()

def _load_documents(config: dict, with_embeddings: bool) -> list[_Doc]:
    include = ["metadatas", "documents"] + (["embeddings"] if with_embeddings else [])
    records = chroma_store.get_all_records(config=config, include=include)
    metadatas = records.get("metadatas")
    texts = records.get("documents")
    embeddings = records.get("embeddings") if with_embeddings else None
    metadatas = [] if metadatas is None else list(metadatas)
    texts = [None] * len(metadatas) if texts is None else list(texts)
    embeddings = [None] * len(metadatas) if embeddings is None else list(embeddings)

    docs: dict[str, _Doc] = {}
    for metadata, text, embedding in zip(metadatas, texts, embeddings):
        if not metadata:
            continue
        doc = docs.get(metadata["doc_id"])
        if doc is None:
            source = metadata["source"]
            path = Path(source)
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) if path.is_file() else None
            doc = _Doc(doc_id=metadata["doc_id"], source=source, modified=modified,
                       metadata={k: v for k, v in metadata.items() if k not in BUILT_IN_METADATA_KEYS})
            docs[doc.doc_id] = doc
        doc.chunks.append((int(metadata.get("chunk_index", 0)), text or "", _vector(embedding)))

    for doc in docs.values():
        doc.chunks.sort(key=lambda chunk: chunk[0])
    return sorted(docs.values(), key=lambda d: d.source)

def _preview(text: str, width: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 3].rstrip() + "..."

class _Builder:
    def __init__(self, policy: PrunePolicy, report: PruneReport):
        self.policy = policy
        self.report = report

    def add(self, doc: _Doc, reason: str, action: PruneAction, signals: dict, group: str | None = None) -> None:
        spec = SEMANTIC_REASONS[reason]
        by_agent = agent_written(doc)
        signals = dict(signals)
        if doc.modified is not None:
            signals["modified"] = doc.modified.date().isoformat()
        signals["agent_written"] = by_agent
        if doc.metadata.get("generated_by"):
            signals["generated_by"] = str(doc.metadata["generated_by"])
        could_run_unattended = (action != PruneAction.NONE and spec.auto_eligible
                                and self.policy.mode(reason) == PruneMode.AUTO)
        candidate = Candidate(target=doc.source, reason=reason, signals=signals, suggested_action=action,
                              group=group, auto_allowed=self.policy.enabled and could_run_unattended and by_agent)
        self.report.candidates.append(candidate)
        if could_run_unattended and not by_agent:
            self.report.held.append(candidate)

def _identical(docs: list[_Doc], build: _Builder) -> set[frozenset[str]]:
    """Whole documents with the same normalised text. The newest file is kept;
    the others are what applying would archive."""
    by_hash: dict[str, list[_Doc]] = {}
    unreadable = 0
    for doc in docs:
        try:
            by_hash.setdefault(text_hash(doc.source), []).append(doc)
        except Exception:
            unreadable += 1
    if unreadable:
        build.report.notes.append(f"{unreadable} document(s) could not be read for the identical-document check.")

    pairs: set[frozenset[str]] = set()
    for digest, group in sorted(by_hash.items(), key=lambda item: item[1][0].source):
        if len(group) < 2:
            continue
        keep = sorted(group, key=lambda d: (-d.modified.timestamp(), d.source))[0]
        group_id = f"identical:{digest[:12]}"
        for doc in sorted(group, key=lambda d: d.source):
            kept = doc is keep
            build.add(doc, DUPLICATE, PruneAction.NONE if kept else PruneAction.ARCHIVE,
                      {"match": "identical document", "chunks": len(doc.chunks), "keep": kept}, group=group_id)
        ids = [d.doc_id for d in group]
        pairs.update(frozenset((a, b)) for a in ids for b in ids if a != b)
    return pairs

def _partial(docs: list[_Doc], threshold: float, model: str, skip: set[frozenset[str]],
             config: dict, build: _Builder) -> None:
    """Passages that two different documents share. Chunks of one document
    overlap by design (`chunk_repeated_words`), so only pairs across
    documents count. Similarity is cosine over the stored embeddings, not the
    collection's distance, which is l2 on vaults made before the switch."""
    by_id = {doc.doc_id: doc for doc in docs}
    # (doc a, doc b) -> best similarity, and which chunks of each matched
    found: dict[tuple[str, str], dict] = {}

    for doc in docs:
        vectors = [(index, vector) for index, _, vector in doc.chunks if vector]
        if not vectors or len(by_id) < 2:
            continue
        result = chroma_store.nearest_other_chunks(
            embeddings=[vector for _, vector in vectors], exclude_doc_id=doc.doc_id,
            config=config, n_results=_NEIGHBOURS)
        rows = zip(*(_rows(result.get(key)) for key in ("metadatas", "embeddings", "documents")))
        for (index, vector), (metadatas, neighbours, texts) in zip(vectors, rows):
            for metadata, neighbour, text in zip(metadatas or [], neighbours if neighbours is not None else [], texts or []):
                other = by_id.get((metadata or {}).get("doc_id"))
                if other is None or other.doc_id == doc.doc_id or frozenset((doc.doc_id, other.doc_id)) in skip:
                    continue
                similarity = _cosine(vector, _vector(neighbour))
                if similarity is None or similarity < threshold:
                    continue
                a, b = sorted((doc.doc_id, other.doc_id))
                entry = found.setdefault((a, b), {"sim": 0.0, "matched": {a: set(), b: set()}, "preview": {}})
                entry["sim"] = max(entry["sim"], similarity)
                entry["matched"][doc.doc_id].add(index)
                entry["matched"][other.doc_id].add(int(metadata.get("chunk_index", 0)))
                own_text = next((t for i, t, _ in doc.chunks if i == index), "")
                entry["preview"].setdefault(doc.doc_id, own_text)
                entry["preview"].setdefault(other.doc_id, text or "")

    for (a, b), entry in sorted(found.items(), key=lambda item: (by_id[item[0][0]].source, by_id[item[0][1]].source)):
        group_id = f"partial:{a[:6]}-{b[:6]}"
        for doc_id in (a, b):
            doc = by_id[doc_id]
            build.add(doc, DUPLICATE_PARTIAL, PruneAction.NONE, {
                "cosine_sim": round(entry["sim"], 4),
                "matched_chunks": len(entry["matched"][doc_id]),
                "total_chunks": len(doc.chunks),
                "threshold": threshold,
                "model": model,
                "preview": _preview(entry["preview"].get(doc_id, "")),
            }, group=group_id)

def _stale(docs: list[_Doc], older_than_days: int, build: _Builder, now: datetime) -> None:
    """Files not modified in `older_than_days`. The file's mtime, not
    `indexed_at`, which resets on every reindex."""
    cutoff = now - timedelta(days=older_than_days)
    for doc in docs:
        if doc.modified < cutoff:
            build.add(doc, STALE, PruneAction.ARCHIVE, {
                "age_days": (now - doc.modified).days,
                "older_than_days": older_than_days,
            })

def find_semantic_candidates(vault_name: str, config: dict, policy: PrunePolicy, reasons: set[str],
                             now: datetime | None = None) -> PruneReport:
    now = now or datetime.now(timezone.utc)
    model = config.get("embedding_model") or DEFAULT_EMBEDDING_MODEL
    wants_partial = DUPLICATE_PARTIAL in reasons and policy.mode(DUPLICATE_PARTIAL) != PruneMode.OFF
    all_docs = _load_documents(config=config, with_embeddings=wants_partial)
    docs = [doc for doc in all_docs if doc.exists]

    report = PruneReport(vault_name=vault_name, policy_enabled=policy.enabled,
                         counts={"documents": len(all_docs), "chunks": sum(len(d.chunks) for d in all_docs)},
                         signals={"model": model})
    build = _Builder(policy=policy, report=report)
    if len(docs) < len(all_docs):
        report.notes.append(f"{len(all_docs) - len(docs)} indexed document(s) have no file on disk and were "
                            "skipped; `ctxvault reindex <vault> --stale` drops them from the index.")

    identical_pairs: set[frozenset[str]] = set()
    if DUPLICATE in reasons and policy.mode(DUPLICATE) != PruneMode.OFF:
        identical_pairs = _identical(docs, build)

    if wants_partial:
        rule = policy.rules.get(DUPLICATE_PARTIAL)
        threshold = (rule.threshold if rule else None) or KNOWN_THRESHOLDS.get(model)
        if threshold is None:
            report.notes.append(f"Partial-overlap check is off: no known threshold for model '{model}'. "
                                "Set one with --threshold.")
        else:
            _partial(docs, threshold, model, identical_pairs, config, build)

    if STALE in reasons and policy.mode(STALE) != PruneMode.OFF:
        rule = policy.rules.get(STALE)
        _stale(docs, (rule.older_than_days if rule else None) or DEFAULT_STALE_DAYS, build, now)

    return report
