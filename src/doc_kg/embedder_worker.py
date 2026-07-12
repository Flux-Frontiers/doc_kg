#!/usr/bin/env python3
"""
embedder_worker.py

CorpusEmbedder — Stage 3 of the multipass analysis pipeline.

Thin re-export of :mod:`kg_utils.corpus_embedder`, the canonical multi-process,
device-safe corpus embedding engine shared across the KGModule stack (doc_kg,
memory_kg, diary_kg). This file used to carry its own copy of ``CorpusEmbedder``
— see CHANGELOG.md for the incident history (a 683k-node consolidated build
OOM'd on Apple Silicon) that forced the device-pinning/GPU-guard/shard-recycling
fixes now centralized in kg_utils. Import from here for backward compatibility,
or from ``kg_utils.corpus_embedder`` directly in new code.

Usage::

    from doc_kg.embedder_worker import CorpusEmbedder

    embedder = CorpusEmbedder(n_workers=4, device="cpu")
    cache = embedder.embed(texts, metadata)
    embedder.save_cache(cache, Path("embeddings.json"))

Author: Eric G. Suchanek, PhD
"""

from __future__ import annotations

from kg_utils.corpus_embedder import CorpusEmbedder, EmbeddingCache

__all__ = ["PIPELINE_MODEL", "CorpusEmbedder", "EmbeddingCache"]

#: Default embedding model for the multipass pipeline.
PIPELINE_MODEL: str = "BAAI/bge-small-en-v1.5"
