"""Episodic vault: statements with a lifetime, not documents with a path.

The primary retrieval path here is structured — entity, validity, source —
because that is what most questions to an episodic memory actually are
("everything about X that still holds"). Semantic similarity is an optional
second path: it only switches on when the vault was created with an embedding
model, so an episodic vault costs nothing to anyone who does not want vectors.
"""

import math
from datetime import datetime, timezone

from ctxvault.core.exceptions import UnsupportedVaultOperationError
from ctxvault.core.vaults.base import BaseVault
from ctxvault.models.episodes import (
    Episode,
    EpisodeHistory,
    EpisodeMatch,
    EpisodeQueryResult,
    VaultEntity,
)
from ctxvault.models.vaults import VaultOperation
from ctxvault.storage import sqlite_store

DEFAULT_LIMIT = 10
DEFAULT_HALF_LIFE_DAYS = 30.0

# Weights for order_by="composite", the relevance/recency/salience blend used by
# retrieval-augmented agents. Callers that want a different balance pass their
# own; the defaults treat the three as equally important.
DEFAULT_WEIGHTS = {"relevance": 1.0, "recency": 1.0, "salience": 1.0}

def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

def _cosine(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return None

    return dot / (norm_a * norm_b)

def _keyword_score(query: str, content: str) -> float:
    """Fallback relevance for vaults without an embedding model.

    Deliberately crude — overlap of distinct words. It keeps `text` usable on a
    vector-free vault without pretending to be semantic search.
    """
    query_words = {w for w in query.casefold().split() if len(w) > 2}
    if not query_words:
        return 0.0

    content_words = {w for w in content.casefold().split() if len(w) > 2}
    return len(query_words & content_words) / len(query_words)

def _recency_score(reference: datetime, moment: str | None, half_life_days: float) -> float:
    """1.0 for something that just happened, halving every `half_life_days`."""
    parsed = _parse_iso(moment)
    if parsed is None:
        return 0.0

    age_days = max((reference - parsed).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / half_life_days) if half_life_days > 0 else 0.0

class EpisodicVault(BaseVault):
    supported_operations = frozenset({
        VaultOperation.WRITE_EPISODE,
        VaultOperation.READ_EPISODE,
        VaultOperation.QUERY_EPISODES,
        VaultOperation.INVALIDATE_EPISODE,
        VaultOperation.SUPERSEDE_EPISODE,
        VaultOperation.REVISE_EPISODE,
        VaultOperation.REINDEX,
    })

    def index_files(self, path: str | None = None) -> tuple[list[str], list[str]]:
        raise UnsupportedVaultOperationError(
            "Episodic vaults store episodes, not files. Use write_episode instead of index."
        )

    def reindex_files(self, path: str | None = None) -> tuple[list[str], list[str]]:
        """For an episodic vault, reindexing means giving a vector to every
        episode that has none: a vault that ran without an embedding model
        and is given one afterwards (`ctxvault reindex <vault>
        --embedding-model ...`) catches up here, and `text` queries become
        semantic from then on. Returns the ids embedded and the ids skipped
        (empty content). Without a model there is nothing to do, and it
        says so rather than pretending."""
        if not self.embedding_model:
            raise UnsupportedVaultOperationError(
                "This episodic vault has no embedding model: set one with "
                "`ctxvault reindex <vault> --embedding-model <sentence-transformers model>`."
            )
        done: list[str] = []
        skipped: list[str] = []
        for row in sqlite_store.episodes_without_embedding(self.config):
            if not row["content"].strip():
                skipped.append(row["id"])
                continue
            sqlite_store.set_embedding(self.config, row["id"], self._embed(row["content"]))
            done.append(row["id"])
        return done, skipped

    @property
    def embedding_model(self) -> str | None:
        # Unlike semantic vaults there is no default: no model configured means
        # no vectors at all, which is a supported way to run an episodic vault.
        return self.config.get("embedding_model")

    def _embed(self, text: str) -> list[float] | None:
        if not self.embedding_model:
            return None

        from ctxvault.core import embedding

        return embedding.embed_list(chunks=[text], model_name=self.embedding_model)[0]

    def _to_episode(self, data: dict) -> Episode:
        return Episode(**{k: v for k, v in data.items() if k != "embedding"})

    def write_episode(
        self,
        content: str,
        *,
        entities: list[str] | None = None,
        source: str | None = None,
        confidence: float = 1.0,
        salience: float = 0.5,
        occurred_at: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        metadata: dict | None = None,
        recorded_at: str | None = None,
    ) -> Episode:
        if not content.strip():
            raise ValueError("Episode content cannot be empty.")

        data = sqlite_store.write_episode(
            self.config,
            content=content,
            entities=entities,
            source=source,
            confidence=confidence,
            salience=salience,
            occurred_at=occurred_at,
            valid_from=valid_from,
            valid_to=valid_to,
            metadata=metadata,
            embedding=self._embed(content),
            recorded_at=recorded_at,
        )
        return self._to_episode(data)

    def get_episode(self, episode_id: str) -> Episode:
        return self._to_episode(sqlite_store.get_episode(self.config, episode_id))

    def invalidate_episode(
        self,
        episode_id: str,
        *,
        valid_to: str | None = None,
        reason: str | None = None,
        at: str | None = None,
    ) -> Episode:
        data = sqlite_store.invalidate_episode(
            self.config, episode_id, valid_to=valid_to, reason=reason, at=at
        )
        return self._to_episode(data)

    def supersede_episode(
        self,
        episode_id: str,
        content: str,
        *,
        entities: list[str] | None = None,
        source: str | None = None,
        confidence: float = 1.0,
        salience: float | None = None,
        occurred_at: str | None = None,
        valid_from: str | None = None,
        metadata: dict | None = None,
        at: str | None = None,
    ) -> Episode:
        if not content.strip():
            raise ValueError("Episode content cannot be empty.")

        data = sqlite_store.supersede_episode(
            self.config,
            episode_id,
            content=content,
            entities=entities,
            source=source,
            confidence=confidence,
            salience=salience,
            occurred_at=occurred_at,
            valid_from=valid_from,
            metadata=metadata,
            embedding=self._embed(content),
            at=at,
        )
        return self._to_episode(data)

    def revise_episode(
        self,
        episode_id: str,
        content: str,
        *,
        entities: list[str] | None = None,
        source: str | None = None,
        confidence: float | None = None,
        salience: float | None = None,
        metadata: dict | None = None,
        at: str | None = None,
    ) -> Episode:
        if not content.strip():
            raise ValueError("Episode content cannot be empty.")

        data = sqlite_store.revise_episode(
            self.config,
            episode_id,
            content=content,
            entities=entities,
            source=source,
            confidence=confidence,
            salience=salience,
            metadata=metadata,
            embedding=self._embed(content),
            at=at,
        )
        return self._to_episode(data)

    def confirm_episode(self, episode_id: str, *, at: str | None = None,
                        source: str | None = None) -> Episode:
        return self._to_episode(
            sqlite_store.confirm_episode(self.config, episode_id, at=at, source=source)
        )

    def dispute_episodes(self, episode_id: str, other_id: str, *, at: str | None = None,
                         note: str | None = None) -> Episode:
        return self._to_episode(
            sqlite_store.dispute_episodes(self.config, episode_id, other_id, at=at, note=note)
        )

    def history(self, episode_id: str) -> EpisodeHistory:
        chain = [self._to_episode(item) for item in sqlite_store.history(self.config, episode_id)]
        return EpisodeHistory(episode_id=episode_id, chain=chain)

    def mark_recalled(self, episode_ids: list[str]) -> None:
        sqlite_store.mark_recalled(self.config, episode_ids)

    def stats(self) -> dict:
        return sqlite_store.count_episodes(self.config)

    def all_episodes(self) -> list[Episode]:
        """The whole vault, newest first: every episode ever recorded, open or
        closed, nothing ranked and nothing truncated. For whoever reads the
        vault whole, the viewer or an export, rather than asking it something."""
        rows = sqlite_store.select_episodes(self.config, include_closed=True, scan_limit=None)
        return [self._to_episode(row) for row in rows]

    def attestations(self) -> list[dict]:
        """Each time a statement was asserted again: episode_id, at, source."""
        return sqlite_store.list_attestations(self.config)

    def disputes(self) -> list[dict]:
        """Each dispute noticed, settled or not: episode_a, episode_b, noticed_at, note."""
        return sqlite_store.list_disputes(self.config)

    def changes(self) -> list[str]:
        """Every instant the vault changed, as ISO timestamps."""
        return sqlite_store.change_moments(self.config)

    def list_entities(
        self,
        *,
        include_closed: bool = False,
        valid_at: str | None = None,
        min_episodes: int = 1,
    ) -> list[VaultEntity]:
        """The vault's vocabulary, most mentioned first.

        Enumeration, not retrieval: a caller that needs to know which names
        exist — to spot them in free text, to offer them as filters, to prune
        what is no longer talked about — asks here rather than paging through
        `query_episodes`, which ranks and truncates.
        """
        rows = sqlite_store.list_entities(
            self.config,
            include_closed=include_closed,
            valid_at=valid_at,
            min_episodes=min_episodes,
        )
        return [VaultEntity(**row) for row in rows]

    def list_metadata_values(
        self,
        key: str,
        *,
        include_closed: bool = False,
        valid_at: str | None = None,
    ) -> list[dict]:
        """The distinct values of one metadata key, with how many episodes
        carry each: enumeration, like `list_entities`, for what the writers
        put in metadata."""
        return sqlite_store.list_metadata_values(
            self.config, key, include_closed=include_closed, valid_at=valid_at
        )

    def query_episodes(
        self,
        text: str | None = None,
        *,
        entities: list[str] | None = None,
        source: str | None = None,
        min_confidence: float | None = None,
        valid_at: str | None = None,
        known_at: str | None = None,
        include_closed: bool = False,
        metadata_filters: dict | None = None,
        disputed: bool | None = None,
        order_by: str | None = None,
        limit: int = DEFAULT_LIMIT,
        half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
        weights: dict | None = None,
        reinforce: bool = False,
    ) -> EpisodeQueryResult:
        candidates = sqlite_store.select_episodes(
            self.config,
            entities=entities,
            source=source,
            min_confidence=min_confidence,
            valid_at=valid_at,
            known_at=known_at,
            include_closed=include_closed,
            metadata_filters=metadata_filters,
            disputed=disputed,
        )

        order = order_by or ("relevance" if text else "recency")
        if order not in {"relevance", "recency", "salience", "composite"}:
            raise ValueError(
                f"Unknown order_by '{order}'. Use relevance, recency, salience or composite."
            )
        if order == "relevance" and not text:
            raise ValueError("order_by='relevance' needs a query text.")

        query_embedding = self._embed(text) if text else None
        reference = _parse_iso(valid_at) or datetime.now(timezone.utc)
        blend = {**DEFAULT_WEIGHTS, **(weights or {})}

        matches: list[EpisodeMatch] = []
        for data in candidates:
            similarity = None
            if text:
                similarity = _cosine(query_embedding, data.get("embedding"))
                if similarity is None:
                    similarity = _keyword_score(text, data["content"])

            recency = _recency_score(reference, data["valid_from"], half_life_days)

            if order == "relevance":
                score = similarity or 0.0
            elif order == "recency":
                score = recency
            elif order == "salience":
                score = data["salience"]
            else:
                score = (
                    blend["relevance"] * (similarity or 0.0)
                    + blend["recency"] * recency
                    + blend["salience"] * data["salience"]
                )

            payload = {k: v for k, v in data.items() if k != "embedding"}
            matches.append(
                EpisodeMatch(**payload, score=score, similarity=similarity, recency=recency)
            )

        matches.sort(key=lambda m: m.score, reverse=True)
        matches = matches[:limit]

        if reinforce and matches:
            self.mark_recalled([m.id for m in matches])

        return EpisodeQueryResult(query=text, order_by=order, results=matches)
