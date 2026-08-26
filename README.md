# ML Project Foundations – Data Quarry

This repository serves as a **shared data repository** for multiple machine learning projects.
Each ML project should live in its own repository and consume data from this repo in a
controlled and reproducible way.


This repository combines application code (src/), dataset-specific developer utilities (data/\<dataset\>/utils/), and a versioned data registry (data/\<dataset\>/) managed with Git and DVC on a per-dataset basis. Dataset tooling is intentionally split: shared dataset management lives in data/, e.g. data/add_dataset.py, while per-dataset helper scripts live only in data/\<dataset\>/utils/.

---

## Setup

Run these commands from the root of this data repository:

```bash
uv sync --all-groups
uv run data-quarry setup
```

`data-quarry setup` stores `DATA_REPO_ROOT` for the current Windows user so that
code in another repository can find this checkout. Restart the terminal after
running it. The DVC data directory is derived as `DATA_REPO_ROOT/data`.

### Repository owner: configure the shared DVC remote

An administrator configures the remote once and commits it:

```bash
uv run data-quarry set-dvc-remote --name storage --url s3://my-company-data/dvc --commit
git push origin main
```

The command adds or updates the default remote and stores it in `.dvc/config`.
Re-running it with the same name changes the remote URL. `--commit` creates the
Git commit but does not push it.

### Developers and CI

Users do not configure the DVC remote. They receive `.dvc/config` through Git.
The environment only needs valid credentials for the configured storage provider,
for example through a cloud login, environment variables, or a CI workload identity.
Secrets must not be committed to `.dvc/config`.

Verify the remote and optionally pull a dataset manually with:

```bash
uv run dvc remote list
uv run dvc pull data/<dataset>/dvc.dvc
```

Application code using `get_file_paths()` performs the required `dvc pull`
automatically.

### Configure the DVC cache location

In some cases, a custom DVC cache directory is required, for example when:

- The data disk is different from the code disk
- Persistent storage is needed (e.g. CI in GitHub Actions or cloud environments)
- Disk space or performance constraints require placing the cache on a specific volume


```bash
dvc config cache.dir /path/to/dvc-cache
```
This writes to .dvc/config (or .dvc/config.local if using --local)

Use `--local` for ephemeral environments (e.g. CI), where configuration should
apply only for the lifetime of the job and must not tracked by git. 

---
## Repository layout

```text
<repo>/
├─ src/                     # Application / library code
├─ data/                    # Dataset registry + dataset folders (see below)
├─ pyproject.toml
├─ README.md                # This file
├─ .dvc/                    # DVC internal metadata (created by `dvc init`)
├─ .gitignore
```

---

## Data layout (data/)
```text
data/
├─ README.md                # Auto-generated dataset index (maintained by add_dataset.py)
├─ add_dataset.py           # Local dev helper for registering & versioning datasets
│
├─ <dataset_name>/          # One dataset per folder
│  ├─ dataset.yaml          # Dataset metadata + component registry + tag history (git-tracked)
│  ├─ README.md             # Dataset documentation (git-tracked, auto-generated)
│  ├─ .gitignore            # Dataset-specific git ignores (git-tracked)
│  ├─ utils/                # Optional helper scripts / code (git-tracked; NOT data)
│  │
│  ├─ dvc/                  # Root for DVC-tracked data; not present after clone and created by `dvc pull`
│  │  ├─ raw/               # Dataset component
│  │  ├─ target/            # Dataset component
│  │  └─ features/          # Dataset component
│  │
│  └─ dvc.dvc               # DVC tracking file for data/<dataset>/dvc (git-tracked)
```
---

## Core conventions

- A dataset can consist of multiple **components**, e.g. `raw`, `target`, `features`.

- The `data/<dataset>dvc/` folder is the root for DVC-tracked data. It is not present after a fresh clone and is created on demand by `dvc pull`.

- Only data under  
  `data/<dataset>/dvc/**`  
  is tracked with DVC.

- Everything else under `data/<dataset>/`  
  (`dataset.yaml`, `README.md`, `utils/`, etc.) is normal Git content.

- A dataset version is represented by a dataset-wide Git tag:  
  `<dataset_name>-vN`

- Dataset versioning is **coarse-grained**:
  - Per-component diffs are not tracked.
  - If any **component** of the dataset data changes, a new dataset version is created.
  - The new dataset tag is appended to all **component** tables (see the next section for details).
  - Dataset versions represent the state of the entire dataset, not individual **components**.

---

## Dataset documentation

Each dataset has an auto-generated README after `add_dataset.py` is invoked:

data/\<dataset\>/README.md

It contains:

- One section per **component** (`raw`, `target`, etc.)
- A **table** per component listing:
  - Folder
  - Description / schema / producer (editable in `dataset.yaml`)
  - Dataset tags (`<dataset>-vN`), where `N` is incremented by 1 for each new dataset version (one row per version)

A new row appearing in a component table implicitly means:

Some **components** of the dataset data changed for that version. As a result, all present components is associated to the new dataset tag, even if only a subset of components changed.

---

## Tooling

### data/add_dataset.py — dataset registration & versioning

A local developer helper used when adding or updating dataset data.
Developers first create or update the relevant folders and files under data/\<dataset\>/dvc/, then run this script to register and version the dataset.

What the script does:

1. Discovers dataset components under:
   data/\<dataset\>/dvc/
2. Runs:
   dvc add data/\<dataset\>/dvc
3. Detects whether dvc.dvc changed
4. If data changed:
   - Increments tag_version in dataset.yaml
   - Produces a new dataset tag: \<dataset\>-vN
5. Appends the dataset tag to all components
6. Regenerates:
   - data/\<datase\>/dataset.yaml
   - data/\<dataset\>/README.md
   - data/README.md (dataset index)

Typical usage:
```bash
uv run python data/add_dataset.py --name some_dataset
```

What it prints:

```bash
git add data/some_dataset/dataset.yaml data/some_dataset/README.md data/README.md
git add data/some_dataset/dvc.dvc
git commit -m "Add/update dataset some_dataset"
git tag some_dataset-v3
```

The user remains in control of committing, tagging and pushing. **Maybe TODO, make this automatic?**

---

### get_file_paths.py — runtime data access helper

Used at runtime (training, evaluation, pipelines) to materialize dataset files for a specific dataset version.

Typically used as:

from data_quarry.tools import get_file_paths

Inputs

- ref — Git commit hash or dataset tag (e.g. dataset1-v3)
- dataset — dataset folder name
- components — list of component names (e.g. ["raw", "target"])

Required environment variable

- DATA_REPO_ROOT — path to the data repository root (where .git and DVC configuration live)

The data directory is derived as `DATA_REPO_ROOT/data`.

Behavior

1. All commands are executed from the correct working directory (CWD).
   The CWD is resolved from DATA_REPO_ROOT and does not rely on the
   caller’s current shell location.
2. Run git checkout <ref>.
3. Run dvc pull data/\<dataset\>/dvc.dvc.
4. Return file paths under data/\<dataset\>/dvc/<component>/**.

**Important:**

This function mutates the repository working tree by design.
It should be used only in controlled environments (local development, CI jobs, containers),
where the correct behavior is enforced via DATA_REPO_ROOT.


---

## Manually working dvc. Not intended or to recommend.

To pull a specific dataset:
```bash
dvc pull data/<dataset_name>
```

⚠️ Avoid running:

```bash
dvc pull
```

This will pull all datasets, which is usually unnecessary and time-consuming.
Datasets are expected to live in remote storage and should only be pulled when needed.


## Component conventions

`raw/`  
Immutable raw input data. Files in this directory must never be modified in place.

`processed/`  
Cleaned, transformed, or feature-engineered data derived from `raw/`.

`target/`  
Ground-truth or label data, e.g. annotations, outcomes, or other target variables derived from the source data.

---

## Design rationale & corner cases

### Configurable cache location
The cache can be configured to live outside the repository. This addresses several practical concerns:

- Persistent storage in cloud environments
- Using local storage on a different disk than the codebase
- Avoiding tight coupling between code location and data storage

Together, these choices make dataset management more flexible and scalable across local development, CI, and cloud setups.


### Corner case: mixed lineage across versions

Example lineage:
raw1 → raw2 → processed1

A dataset tag represents a coherent snapshot of the dataset at a point in time. In the latest snapshot we may have components {raw2, processed1}. If we want to use {raw1, processed1}, that combination is not represented by a single tag.

This is not necessarily a design flaw. The intent is that versions are snapshots, not a composable graph of components. Mixing an older raw component with a newer derived component typically does not make sense, because the derived component (processed1) is expected to correspond to the raw state in the same snapshot.

In other words, it is generally safe to assume that the latest snapshot “covers” the old one, and that selecting raw1 together with processed1 is either invalid or a debugging-only workflow, not something the versioning model needs to support.

The dataset README shows how components evolve over time.

### Design tradeoff: dataset-wide pulls vs component-level pulls

With the current design, we pull at dataset granularity (e.g. `dvc pull data/<dataset>/dvc.dvc`), which materializes all components of that dataset (raw, target, processed, etc.). This can look wasteful if a job only needs a subset of components.

In practice, this is usually acceptable because DVC relies on a cache. In persistent environments (local machines, long-lived training servers, or cloud runners with a stable cache), repeated pulls are incremental and deduplicated, so “pull everything” is simpler without a large ongoing cost.

Where this can become a limitation is on constrained or ephemeral environments:
- machines with limited disk where each training run must pull data and then delete it afterwards
- jobs where we intentionally avoid keeping a local cache between runs

But these are uncommon corner cases. 

### Coarse-grained versioning is intentional.
If any component of a dataset changes, a new dataset version is created. Per-component diffs are not tracked. This keeps reproducibility simple and avoids invalid combinations of components.

### Multiple datasets, different versions are supported.
Training or evaluation can safely use multiple datasets at different tags, since each dataset lives in its own folder and it is assumed one tag is for one \<dataset\> only.

### Multiple versions of the same dataset in one run are out of scope.
This is not considered an important use case. Using directly using cache paths is not safe. If ever needed, it should be handled via separate checkouts, not within a single working tree.  

### Dataset-wide DVC pulls trade granularity for simplicity.
dvc pull data/\<dataset\>/dvc.dvc materializes all components of a dataset. This is usually acceptable because DVC caches data efficiently in persistent environments. Finer-grained should not be needed since we assume data lineage should cover old verisions. 

### Ephemeral environments (CI)
Ephemeral environments are supported by design through the use of environment variables, ensuring correct behavior without relying on persistent state.

In CI, the data repository is checked out per job, required data is pulled on demand, and everything is discarded afterward. Caching the DVC cache is an optional optimization to speed up repeated runs, not a requirement for correctness.

### Working tree mutation is explicit and controlled.
Runtime helpers (e.g. get_file_paths) intentionally mutate the data repo working tree. They should be used only in controlled environments and are not safe for concurrent use against the same checkout.

---

## TODOs
- Migrate to cloud
- Document how to use this repository from another repository’s CI pipeline (e.g. GitHub Actions):
  - Check out the code repo
  - Check out this data repo into a subfolder (e.g. _data_repo) with tags (fetch-depth: 0)
  - Set DATA_REPO_ROOT to that checkout
  - Run tests/integration steps that call get_file_paths()
  - (Optional) cache DVC cache to speed up repeated runs

