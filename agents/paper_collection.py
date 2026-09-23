"""
Paper Collection Agent (Phase 2, Step 1)

Responsibilities:
1. Extract search keywords from the user's vague topic [LOCAL]
2. Search every configured paper source (tools/sources), paced and
   block-aware per tools/rate_limit.py
3. Canon-seed: supplement with highly-cited foundational papers via
   Semantic Scholar, since keyword/recency search alone misses them
   (see tools/semantic_scholar.py for why)
4. Embed papers and store in ChromaDB
5. Select top-K papers by similarity to the topic, with canon-seeded
   papers guaranteed to survive the top-K cut
6. Download PDFs only for selected arXiv papers
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from tools.arxiv_fetcher import ArxivFetcher, PaperRecord
from tools.rate_limit import SourceBlocked

if TYPE_CHECKING:
    from models.local_model import LocalModel, EmbeddingModel
    from memory.vector_db import VectorDB
    from memory.note_db import NoteDB

import config

logger = logging.getLogger(__name__)
console = Console()


class PaperCollectionAgent:

    def __init__(
        self,
        local_model: "LocalModel",
        embed_model: "EmbeddingModel",
        vector_db: "VectorDB",
        note_db: "NoteDB",
        top_k: int = config.ARXIV_TOP_K,
    ) -> None:
        self._local = local_model
        self._embed = embed_model
        self._vdb = vector_db
        self._ndb = note_db
        self._top_k = top_k
        self._fetcher = ArxivFetcher()
        self._deg = None  # set per-run in run(); see agents/degradation.py

    # ------------------------------------------------------------------
    def run(self, topic: str, session_id: str) -> list[PaperRecord]:
        """
        Full pipeline: keywords → fetch → embed → cluster → top-K.
        Returns the selected top-K PaperRecords.
        """
        from agents.degradation import DegradationLog
        self._deg = DegradationLog(self._ndb, session_id, notify=console.print)

        console.print(f"\n[bold cyan][Paper Collection][/] Topic: {topic}")

        # Step 1: keyword extraction
        keywords = self._extract_keywords(topic)
        console.print(f"  Keywords: {', '.join(keywords)}")

        # Step 2: search every configured source (paced per source; blocked
        # or unconfigured sources are skipped and recorded, not retried)
        from tools.sources import deduplicate, search_all
        all_papers: list[PaperRecord] = []
        problems: dict[str, str] = {}
        for kw in keywords[:3]:  # use up to 3 keyword variants
            papers, kw_problems = search_all(kw)
            all_papers.extend(papers)
            for source, reason in kw_problems.items():
                problems.setdefault(source, reason)

        all_papers = deduplicate(all_papers)
        used = [s for s in config.PAPER_SOURCES if s not in problems]
        for source, reason in problems.items():
            self._deg.record(1, f"source:{source}", "warn", f"{source} skipped: {reason}")
        if not used:
            self._deg.record(
                1, "sources", "critical",
                "No paper source was usable (all blocked, unconfigured, or failing). "
                "Collection is empty or limited to canon seeding."
            )
        console.print(
            f"  Fetched [green]{len(all_papers)}[/] unique papers from "
            f"{', '.join(used) or 'no sources'}."
        )

        # Step 2.5: canon-seed with highly-cited foundational papers
        canon_ids: set[str] = set()
        if config.CANON_SEED_ENABLED:
            canon_papers = self._fetch_canonical(topic)
            if canon_papers:
                console.print(
                    f"  Canon-seeding: [green]{len(canon_papers)}[/] highly-cited "
                    f"foundational paper(s) added (keyword search alone would have missed these)."
                )
                all_papers, canon_ids = self._merge_canon(all_papers, canon_papers)

        if not all_papers:
            logger.warning("No papers found for topic: %s", topic)
            return []

        # Step 3: embed & store in ChromaDB
        console.print("  Embedding papers…")
        self._embed_and_store(all_papers, session_id)

        # Step 4: select top-K by query similarity (canon papers always survive)
        top_papers = self._select_top_k(topic, all_papers, must_include_ids=canon_ids)
        console.print(
            f"  Selected [green]{len(top_papers)}[/] papers for review."
        )

        # Step 4.5: PDFs only for arXiv papers that survived ranking —
        # never for the whole candidate pool, to keep request count minimal.
        self._download_pdfs(top_papers)

        # Step 5: persist to SQLite
        for paper in top_papers:
            if not self._ndb.paper_exists(session_id, paper.arxiv_id):
                self._ndb.save_paper(session_id, paper.to_dict())

        return top_papers

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ascii_safe(text: str, max_len: int = 100) -> str:
        """Strip non-ASCII characters and truncate to max_len.

        arXiv's API returns HTTP 500 when the query contains non-ASCII
        (e.g. Korean/Chinese/Japanese) characters or is excessively long.
        """
        import re as _re
        # Keep only printable ASCII: letters, digits, spaces, common punctuation
        cleaned = _re.sub(r'[^\x20-\x7E]', ' ', text)
        # Collapse runs of whitespace
        cleaned = _re.sub(r'\s+', ' ', cleaned).strip()
        # Remove markdown bold/italic markers that the LLM sometimes includes
        cleaned = _re.sub(r'\*+', '', cleaned).strip()
        return cleaned[:max_len]

    def _extract_keywords(self, topic: str) -> list[str]:
        """Use local model to generate 3 English search keyword variants."""
        # Ensure the topic itself is ASCII-safe before sending to LLM or arXiv
        safe_topic = self._ascii_safe(topic, max_len=200)

        prompt = (
            "You are a research assistant. Given a research topic, generate "
            "3 distinct SHORT arXiv search query strings (English only, max 10 words each) "
            "that will find the most relevant papers.\n\n"
            f"Topic: {safe_topic}\n\n"
            "Rules:\n"
            "- ALL output must be in English only\n"
            "- Each query must be short (≤10 words) and contain only ASCII characters\n"
            "- Output ONLY a JSON array of 3 strings, no explanation\n"
            'Example: ["transformers reinforcement learning", '
            '"transformer policy gradient survey", '
            '"attention mechanism RL benchmark"]'
        )

        if self._local and self._local.is_loaded:
            raw = self._local.generate(prompt, temperature=0.1)
        else:
            # fallback: simple split
            raw = f'["{safe_topic}", "{safe_topic} survey", "{safe_topic} deep learning"]'

        # parse JSON array from response
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if match:
            import json
            try:
                keywords = json.loads(match.group())
                if isinstance(keywords, list) and keywords:
                    # Sanitize every keyword: ASCII-only, short
                    safe_kws = [
                        self._ascii_safe(str(k), max_len=80)
                        for k in keywords[:3]
                        if str(k).strip()
                    ]
                    # Filter out empty or too-short keywords
                    safe_kws = [k for k in safe_kws if len(k) > 3]
                    if safe_kws:
                        return safe_kws
            except Exception:
                pass

        logger.warning("Keyword extraction fallback for topic: %s", safe_topic)
        return [safe_topic, f"{safe_topic} survey", f"{safe_topic} deep learning"]

    def _embed_and_store(
        self, papers: list[PaperRecord], session_id: str
    ) -> None:
        """Embed each paper and upsert into ChromaDB."""
        batch: list[dict] = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("  Embedding…", total=len(papers))

            for paper in papers:
                text = paper.embed_document
                try:
                    embedding = self._embed.embed(text)
                except Exception as exc:
                    logger.warning("Embedding failed for %s: %s", paper.arxiv_id, exc)
                    progress.advance(task)
                    continue

                batch.append({
                    "arxiv_id":  paper.arxiv_id,
                    "document":  text,
                    "embedding": embedding,
                    "metadata": {
                        "title":      paper.title,
                        "authors":    ", ".join(paper.authors[:5]),
                        "year":       paper.year,
                        "url":        paper.url,
                        "session_id": session_id,
                    },
                })
                progress.advance(task)

        if batch:
            self._vdb.add_papers_batch(batch)

    def _select_top_k(
        self,
        topic: str,
        papers: list[PaperRecord],
        must_include_ids: set[str] | None = None,
    ) -> list[PaperRecord]:
        """
        Rank papers by cosine similarity to the topic embedding, return the
        top-K. Any id in `must_include_ids` (canon-seeded papers) is placed
        first and is guaranteed to survive the top-K cut, since a highly-cited
        foundational paper ranking low on raw topic-embedding similarity is a
        ranking-quality problem, not a reason to drop it.

        Papers scoring more than config.RELEVANCE_MARGIN below the best
        non-canon paper are dropped rather than padding the result up to
        top_k — a 2026-09-12 test session found that silently backfilling
        with the "least bad" off-topic papers produced a 30%-precision
        collection with no indication anything was wrong. The cut is relative
        to the top score because embedding models compress similarities
        differently; an absolute floor that works for one model removes
        nothing (or everything) for another.
        """
        must_include_ids = must_include_ids or set()
        ranked, sims = self._rank_all(topic, papers)

        id_to_paper = {p.arxiv_id: p for p in papers}
        canon_first = [id_to_paper[aid] for aid in must_include_ids if aid in id_to_paper]

        if sims is None:
            # Ranking couldn't run at all (already recorded as a critical
            # degradation in _rank_all) — fall back to the sources' own order
            # rather than returning nothing.
            rest = [p for p in ranked if p.arxiv_id not in must_include_ids]
            combined = canon_first + rest
            budget = max(self._top_k, len(canon_first))
            return combined[:budget]

        scored = [(p, s) for p, s in zip(ranked, sims) if p.arxiv_id not in must_include_ids]
        cutoff = (max(s for _, s in scored) - config.RELEVANCE_MARGIN) if scored else 0.0
        survivors = [p for p, s in scored if s >= cutoff]

        if len(survivors) < self._top_k and self._deg:
            self._deg.record(
                1, "relevance_margin", "warn",
                f"Only {len(survivors)} of {len(papers)} collected papers scored within "
                f"{config.RELEVANCE_MARGIN} of the best match (cutoff {cutoff:.3f}); "
                f"requested top-{self._top_k}. Returning {len(survivors)} rather than "
                f"padding with papers the topic embedding ranked well below — this "
                f"topic's literature may not be well covered by the sources searched."
            )

        combined = canon_first + survivors
        return combined[: max(self._top_k, len(canon_first))]

    def _rank_all(
        self, topic: str, papers: list[PaperRecord]
    ) -> tuple[list[PaperRecord], list[float] | None]:
        """
        Rank ALL papers by cosine similarity to the topic embedding (no
        truncation). Returns (ranked_papers, similarities) aligned
        index-for-index, or (papers, None) if ranking could not run at all.

        This used to delegate to self._vdb.query() — in the Web UI, which
        never loads a real vector DB (`_DummyVectorDB.query()` always
        returns `[]`), that silently degraded to "keep arXiv's own order"
        with nothing recorded anywhere that ranking never ran. Computing
        cosine similarity directly from self._embed removes the vector-DB
        dependency for ranking entirely — re-ranking ~100 candidates needs
        no index — and lets a degenerate (all-zero) embedding backend be
        caught explicitly instead of masquerading as "ranked."
        """
        import numpy as np

        try:
            topic_vec = np.asarray(self._embed.embed(topic), dtype=np.float32)
        except Exception as exc:
            if self._deg:
                self._deg.record(
                    1, "ranking", "critical",
                    f"Topic embedding failed ({exc}). Papers are UNRANKED — order "
                    f"reflects arXiv's own result order, not relevance to the topic."
                )
            return list(papers), None

        if float(np.linalg.norm(topic_vec)) < 1e-8:
            if self._deg:
                self._deg.record(
                    1, "ranking", "critical",
                    "The embedding backend returned an all-zero vector for the topic. "
                    "Papers are UNRANKED — order reflects arXiv's own result order, not "
                    "relevance to the topic."
                )
            return list(papers), None

        keep: list[PaperRecord] = []
        vecs = []
        for p in papers:
            try:
                v = np.asarray(self._embed.embed(p.embed_document), dtype=np.float32)
            except Exception:
                continue
            if float(np.linalg.norm(v)) < 1e-8:
                continue
            keep.append(p)
            vecs.append(v)

        if not keep:
            if self._deg:
                self._deg.record(
                    1, "ranking", "critical",
                    "No paper embeddings were usable. Papers are UNRANKED."
                )
            return list(papers), None

        matrix = np.vstack(vecs)
        matrix = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9)
        q = topic_vec / (np.linalg.norm(topic_vec) + 1e-9)
        sims = matrix @ q
        order = np.argsort(-sims)
        ranked = [keep[i] for i in order]
        ranked_sims = [float(sims[i]) for i in order]

        # Papers whose embedding failed still need to appear somewhere —
        # append below every successfully-ranked paper, never above.
        kept_ids = {p.arxiv_id for p in keep}
        missing = [p for p in papers if p.arxiv_id not in kept_ids]
        if missing:
            ranked.extend(missing)
            ranked_sims.extend([0.0] * len(missing))

        return ranked, ranked_sims

    def _download_pdfs(self, papers: list[PaperRecord]) -> None:
        """Download PDFs for selected arXiv papers; stop at the first block."""
        targets = [p for p in papers if p.source == "arxiv" and not p.pdf_path]
        if not targets:
            return
        console.print(f"  Downloading {len(targets)} arXiv PDF(s) (paced 20-30 s apart)…")
        for p in targets:
            try:
                p.pdf_path = self._fetcher.download_pdf(p)
            except SourceBlocked as exc:
                if self._deg:
                    self._deg.record(
                        1, "source:arxiv", "warn",
                        f"PDF downloads stopped: {exc}. Remaining papers use abstracts only.",
                    )
                return

    def _fetch_canonical(self, topic: str) -> list[PaperRecord]:
        """Best-effort fetch of highly-cited foundational papers. Never raises."""
        try:
            from tools.semantic_scholar import SemanticScholarFetcher
            safe_topic = self._ascii_safe(topic, max_len=200)
            fetcher = SemanticScholarFetcher()
            papers = fetcher.search_top_cited(
                safe_topic,
                limit=config.CANON_SEED_COUNT,
                min_citation_count=config.CANON_MIN_CITATIONS,
            )
        except Exception as exc:
            logger.warning("Canon seeding failed, continuing without it: %s", exc)
            if self._deg:
                self._deg.record(
                    1, "canon_seeding", "critical",
                    f"Semantic Scholar unreachable ({exc}). No highly-cited canon papers "
                    f"were added; collection relies on keyword search alone."
                )
            return []

        if not papers and self._deg:
            self._deg.record(
                1, "canon_seeding", "critical",
                "Semantic Scholar returned 0 papers for this topic. No highly-cited canon "
                "papers were added; collection relies on keyword search alone."
            )
        return papers

    @staticmethod
    def _merge_canon(
        all_papers: list[PaperRecord], canon_papers: list[PaperRecord]
    ) -> tuple[list[PaperRecord], set[str]]:
        """
        Merge canon-seeded papers into the collected set, deduplicating by
        arxiv_id and (as a fallback, since Semantic Scholar entries may lack
        an arXiv id or use a different id format) by normalized title.
        Returns (merged_papers, canon_ids) where canon_ids covers both newly
        added papers and pre-existing ones matched by title.
        """
        def _norm_title(t: str) -> str:
            return re.sub(r'[^a-z0-9]', '', t.lower())

        existing_ids = {p.arxiv_id for p in all_papers}
        existing_titles = {_norm_title(p.title): p.arxiv_id for p in all_papers}

        merged = list(all_papers)
        canon_ids: set[str] = set()

        for cp in canon_papers:
            if cp.arxiv_id in existing_ids:
                canon_ids.add(cp.arxiv_id)
                continue
            norm = _norm_title(cp.title)
            existing_match = existing_titles.get(norm)
            if existing_match:
                canon_ids.add(existing_match)  # already present under a different id
                continue
            merged.append(cp)
            existing_ids.add(cp.arxiv_id)
            existing_titles[norm] = cp.arxiv_id
            canon_ids.add(cp.arxiv_id)

        return merged, canon_ids
