---
name: imap_unordered fix needed
description: _embed_parallel uses pool.imap which blocks on the slowest shard — fix to imap_unordered
type: project
---

`CorpusEmbedder._embed_parallel()` in `src/doc_kg/embedder_worker.py` uses `pool.imap(_embed_shard, shards)` which yields results in order, blocking on slow shards even when faster ones are done.

**Fix:** change `_embed_shard` to return `(worker_id, vectors)` tuple, use `pool.imap_unordered`, reassemble by worker_id.

```python
# _embed_shard: change return to (worker_id, vectors)
return worker_id, [np.asarray(v, dtype="float32").tolist() for v in vecs]

# _embed_parallel: reassemble unordered results
results: dict[int, list] = {}
with Progress(...) as progress:
    task = progress.add_task(f"  Embedding ({len(shards)} workers)", total=len(texts))
    for worker_id, shard_vecs in pool.imap_unordered(_embed_shard, shards):
        results[worker_id] = shard_vecs
        progress.advance(task, shard_lengths[worker_id])

# reassemble in shard order
all_vectors = []
for i in range(len(shards)):
    all_vectors.extend(results[i])
```

**Why:** with 8 shards, the 4th can block 5-8 even if they finished, causing long apparent stalls in the progress bar.
