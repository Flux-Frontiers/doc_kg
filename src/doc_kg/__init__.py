"""
DocKG — Document Knowledge Graph

Builds a semantically searchable knowledge graph from .md and .txt files.
Same architecture as CodeKG, adapted for natural-language documents.

Pipeline:
    corpus → DocGraph (chunker) → GraphStore (SQLite) → SemanticIndex (LanceDB)

Key classes:
    DocKG       — top-level orchestrator
    DocGraph    — corpus parsing and chunking
    GraphStore  — SQLite persistence
    SemanticIndex — LanceDB vector index + SIMILAR_TO edge discovery
    TextChunker — semantic text segmentation

Author: Eric G. Suchanek, PhD
"""

from doc_kg.dockg import DEFAULT_MODEL, DocEdge, DocNode
from doc_kg.graph import DocGraph
from doc_kg.index import Embedder, SemanticIndex, SentenceTransformerEmbedder
from doc_kg.kg import BuildStats, DocKG, QueryResult, TextPack
from doc_kg.store import GraphStore
from doc_kg.topics import TopicExtractor

__all__ = [
    "DocKG",
    "DocGraph",
    "GraphStore",
    "SemanticIndex",
    "SentenceTransformerEmbedder",
    "Embedder",
    "DocNode",
    "DocEdge",
    "BuildStats",
    "QueryResult",
    "TextPack",
    "DEFAULT_MODEL",
    "TopicExtractor",
]
