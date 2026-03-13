# DocKG Temporal Snapshots

**Enterprise-Grade Metrics Tracking Across Commits**

Capture, store, and compare document corpus metrics over time. Track the evolution of topic coverage, entity density, and documentation health signals from version to version.

---

## Overview

Snapshots are point-in-time captures of your document corpus's metrics, tagged with:
- **Commit hash** — for version control integration
- **Branch name** — to distinguish release vs. develop metrics
- **Version string** — semantic versioning (0.5.1, 1.0.0, etc.)
- **Timestamp** — ISO 8601 UTC for auditability
- **Full metrics** — nodes, edges, coverage, complexity, hotspots

Each snapshot includes **automatic delta computation** against the previous snapshot and a baseline snapshot, showing trends over time.

---

## Quick Start

### Capture a Snapshot
```bash
dockg snapshot save 0.5.1
```

Automatically detects your current git commit and branch. Creates `.dockg/snapshots/{commit}.json` with full metrics.

### List All Snapshots
```bash
dockg snapshot list
```

Shows all snapshots in reverse chronological order:
```
Commit     Branch       Version    Nodes  Edges  Coverage
3487ed5    develop      0.5.1      3818   3717   97.0%
660e4f0    main         0.5.0      3818   3717   97.0%
9f7918d    develop      0.4.0      3750   3650   95.2%
```

### Show Snapshot Details
```bash
dockg snapshot show 3487ed5
```

Displays full metrics, hotspots, and deltas:
```
Commit:    3487ed5
Branch:    develop
Timestamp: 2026-03-07T17:25:29Z
Version:   0.5.1

Metrics:
  Total Nodes:       3818
  Total Edges:       3717
  Docstring Coverage: 97.0%
  Critical Issues:   0

Delta vs. Previous:
  Nodes:    +25
  Edges:    +67
  Coverage: +0.2%
  Issues:   0
```

### Compare Two Snapshots
```bash
dockg snapshot diff 660e4f0 3487ed5
```

Side-by-side comparison showing what changed:
```
Comparing 660e4f0 vs 3487ed5

Metric                   A             B             Δ
total_nodes              3750          3818          +68
total_edges              3650          3717          +67
docstring_coverage       96.8%         97.0%         +0.2%
critical_issues          1             0             -1
```

---

## Architecture

### Storage Structure
```
.dockg/
├── graph.sqlite          # Knowledge graph database
├── lancedb/              # Semantic embeddings
└── snapshots/
    ├── manifest.json     # Index of all snapshots
    ├── 3487ed5.json      # Snapshot by commit hash
    ├── 660e4f0.json
    └── 9f7918d.json
```

### Manifest Index
```json
{
  "format": "1.0",
  "last_update": "2026-03-07T17:25:29Z",
  "snapshots": [
    {
      "commit": "3487ed5",
      "branch": "develop",
      "timestamp": "2026-03-07T17:25:29Z",
      "version": "0.5.1",
      "file": "3487ed5.json",
      "metrics": {
        "nodes": 3818,
        "edges": 3717,
        "coverage": 0.97,
        "critical_issues": 0
      },
      "deltas": {
        "vs_previous": {
          "nodes": 25,
          "edges": 67,
          "coverage_delta": 0.002,
          "critical_issues_delta": -1
        },
        "vs_baseline": {
          "nodes": 68,
          "edges": 67,
          "coverage_delta": 0.019,
          "critical_issues_delta": -1
        }
      }
    }
  ]
}
```

### Snapshot Schema
Each snapshot captures:

**Metrics**
- `total_nodes` — Total nodes in graph (including symbols)
- `meaningful_nodes` — Nodes excluding infrastructure stubs
- `total_edges` — Total edges in graph
- `node_counts` — Breakdown by kind (class, function, method, module, symbol)
- `edge_counts` — Breakdown by relation (CALLS, CONTAINS, IMPORTS, INHERITS, ATTR_ACCESS, RESOLVES_TO)
- `docstring_coverage` — Percentage of documented entities (0.0–1.0)
- `critical_issues` — Count of critical issues found
- `complexity_median` — Median fan-in across functions

**Deltas**
- `vs_previous` — Changes from previous snapshot
- `vs_baseline` — Changes from oldest (baseline) snapshot

---

## Usage Patterns

### Release Management
Track metrics at each version release:

```bash
# After tagging v0.5.1
dockg snapshot save 0.5.1

# After tagging v0.5.2
dockg snapshot save 0.5.2

# Compare releases
dockg snapshot diff <v0.5.1-commit> <v0.5.2-commit>
```

### Feature Branch Tracking
Monitor complexity as features are added:

```bash
# On feature/add-caching
codekg build --repo .
dockg snapshot save 0.5.2-dev1

# After optimization work
codekg build --repo .
dockg snapshot save 0.5.2-dev2

# See improvement
dockg snapshot diff <dev1-commit> <dev2-commit>
```

### Regression Detection
Identify when metrics degrade:

```bash
# Weekly health check
codekg build --repo .
dockg snapshot save 0.5.1-week5

# Compare to last week
dockg snapshot diff <prev-week-commit> <current-week-commit>

# Alert if critical_issues increased or coverage dropped
```

### Automatic Capture via Git Hook (Recommended)

Install the post-commit hook once and snapshots are captured automatically after every commit — tagged with the real commit hash:

```bash
codekg install-hooks
```

After each `git commit`, the hook runs silently in the background:
1. Reads the version from `pyproject.toml`
2. Tags the snapshot with the actual commit hash
3. Saves to `.dockg/snapshots/` (local only — not staged or committed)

The hook never blocks commits — if the graph isn't built yet, it prints a warning and exits cleanly.

Snapshots are local artifacts by default (`.dockg/` is gitignored). Commit them manually at milestones if you want git history:
```bash
git add .dockg/snapshots/ && DOCKG_SKIP_SNAPSHOT=1 git commit -m "chore: capture snapshot"
```

To overwrite an existing hook:
```bash
codekg install-hooks --force
```

### CI/CD Integration
Automate snapshot capture in your pipeline:

```bash
#!/bin/bash
# In GitHub Actions or CI workflow

# Build graph
codekg build --repo . --wipe

# Capture snapshot
VERSION=$(git describe --tags --always)
dockg snapshot save $VERSION

# Compare to previous
PREV_TAG=$(git describe --tags --abbrev=0 HEAD~1)
dockg snapshot diff $PREV_TAG $VERSION > metrics_comparison.txt
```

---

## API Usage

### Python Integration

```python
from doc_kg.snapshots import SnapshotManager

# Initialize manager
mgr = SnapshotManager(".dockg/snapshots")

# Capture snapshot
snapshot = mgr.capture(
    version="0.5.1",
    commit="3487ed5",        # auto-detected if None
    branch="develop",         # auto-detected if None
    graph_stats_dict={...},
    coverage=0.97,
    critical_issues=0,
    complexity_median=4.2,
)
mgr.save_snapshot(snapshot)

# Load and inspect
manifest = mgr.load_manifest()
previous = mgr.get_previous("3487ed5")
baseline = mgr.get_baseline()

# Compare
diff = mgr.diff_snapshots("660e4f0", "3487ed5")

# List all
snapshots = mgr.list_snapshots(limit=10)
```

### JSON Output

All snapshot commands support `--json` for machine consumption:

```bash
dockg snapshot list --json > snapshots.json
dockg snapshot show 3487ed5 > snapshot_detail.json
dockg snapshot diff a b --json > comparison.json
```

---

## Metrics Explained

### Node/Edge Counts
- **Nodes** — Total entities in the knowledge graph
- **Meaningful Nodes** — Real code entities (excludes symbol infrastructure)
- **Edges** — Relationships between nodes

Increasing nodes/edges indicates code growth. Decreasing suggests refactoring or cleanup.

### Docstring Coverage
Percentage of documented functions, classes, and methods.

- **97%+** — Excellent (most entities have docstrings)
- **90-97%** — Good (well documented)
- **80-90%** — Fair (gaps in documentation)
- **<80%** — Poor (incomplete documentation)

### Critical Issues
Count of high-risk patterns found during analysis:
- High complexity functions (fan-out > 10)
- Circular dependencies
- Orphaned code
- Dead functions

Lower is better. Trends indicate code health improvements or regressions.

### Complexity Median
Median fan-in (number of callers) across all functions.

- **2-4** — Healthy (good separation of concerns)
- **5-8** — Moderate (some coordination functions)
- **>8** — High (risk of coupling)

---

## Deltas and Trends

Snapshots automatically compute deltas:

**vs_previous**
- Change from the immediately previous snapshot
- Useful for detecting what changed in the last commit/PR
- Example: "Coverage improved 0.5%, added 12 nodes"

**vs_baseline**
- Change from the oldest snapshot
- Shows overall trajectory since project start
- Example: "Growth of +500 nodes, coverage improved 5% over 6 months"

Monitor trends to detect:
- ✅ Improving coverage over time
- ✅ Stable complexity
- ⚠️ Growing critical issues
- ⚠️ Increasing fan-out (coupling)

---

## Best Practices

1. **Install the git hook**
   - Run `codekg install-hooks` once per repo
   - Snapshots are captured automatically after every commit into `.dockg/snapshots/`
   - They stay local (gitignored) — no staging friction

2. **Capture at milestones**
   - Tag releases with versions
   - Snapshot after major refactoring
   - Weekly health checks for long-running projects

2. **Use semantic versioning**
   - `0.5.1` for releases
   - `0.5.2-dev` for development snapshots
   - Easier to track release impact

3. **Include context**
   - Use branch names to distinguish develop/main
   - Tag with what changed if committing snapshots
   - Link to issues/PRs for traceability

4. **Automate in CI**
   - Capture snapshot after every release
   - Set up alerts for regressions
   - Archive artifacts for historical analysis

5. **Analyze trends**
   - Monthly review of metric trajectories
   - Celebrate improvements (coverage up 2%)
   - Address regressions quickly

---

## Common Questions

**Q: How often should I capture snapshots?**
A: At version releases (mandatory), weekly for long projects, after major changes (optional). More frequent = better granularity, but storage is minimal.

**Q: Can I commit snapshots to git?**
A: Yes, optionally. By default `.dockg/` is gitignored — snapshots are local artifacts. To commit at a milestone: `git add .dockg/snapshots/ && DOCKG_SKIP_SNAPSHOT=1 git commit -m "chore: capture snapshot"`. The `DOCKG_SKIP_SNAPSHOT=1` env var prevents the post-commit hook from running again and creating new unstaged files.

**Q: What if I miss a snapshot?**
A: You can manually create one anytime with `dockg snapshot save`. Delta comparison still works as long as timestamps are preserved.

**Q: How do I integrate with dashboards?**
A: Use `--json` output and feed to Grafana, Datadog, or custom tools. The structure is designed for programmatic ingestion.

**Q: Can I delete or modify snapshots?**
A: Snapshots are write-once by design. Create new ones instead. If you need to remove snapshots, delete the JSON file and update manifest.json.

---

## See Also

- [Architecture Analysis](ARCHITECTURE.md) — Generate architectural descriptions
- [CHEATSHEET.md](CHEATSHEET.md) — CodeKG query reference
- [README.md](../README.md) — Project overview
