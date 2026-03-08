# Automated Temporal Snapshots (GitHub Actions)

Snapshots are automatically captured on every commit to the `develop` branch via GitHub Actions CI.

## How It Works

The **Temporal Snapshots** workflow (`.github/workflows/snapshots.yml`):

1. **Triggers on:** Every push to `develop` branch or manual workflow dispatch
2. **Builds:** DocKG database (SQLite + LanceDB vector index)
3. **Runs analysis:** Generates a Markdown report capturing current corpus metrics:
   - Total nodes/edges
   - Semantic coverage (topic, entity, keyword)
   - Top documents by chunk count
   - Hot chunks
4. **Archives:** Report and `.dockg/` index as build artifact (90-day retention)

## Snapshot Contents

Each analysis report captures:

- **Commit hash** — Immutable git reference (via artifact metadata)
- **Timestamp** — ISO 8601 UTC for auditability
- **Version** — Semantic version from `pyproject.toml`
- **Metrics** — Full graph statistics and analysis results

## Viewing Results

### In GitHub Actions

Snapshots are available as artifacts in the workflow run:

1. Go to **Actions** → **Temporal Snapshots**
2. Click any run to view results
3. Download `dockg-snapshots-<commit>` artifact

### Via CLI

```bash
# Re-run analysis locally
dockg-analyze . --output analysis/latest.md
```

## Manual Trigger

Trigger the workflow manually without a commit:

- **Actions** → **Temporal Snapshots** → **Run workflow**

## Configuration

### Trigger Branches

Edit `.github/workflows/snapshots.yml` to change trigger branches:

```yaml
on:
  push:
    branches: [develop, main, release/*]
```

### Artifact Retention

Snapshots are kept for 90 days:

```yaml
retention-days: 90
```

## Troubleshooting

### Workflow didn't run
- Check branch name matches `on.push.branches`
- Manual trigger: **Actions** → **Temporal Snapshots** → **Run workflow**

### Build failed
- Check `dockg-build-graph` / `dockg-build-index` output in logs
- Artifact will still be uploaded for partial results if analysis ran

### Out of space on runner
- Large corpora may need more disk
- Check `.dockg/lancedb/` size

## See Also

- [MCP Setup Guide](../docs/MCP.md) — Connecting DocKG to AI agents
- [README](../README.md) — Project overview
