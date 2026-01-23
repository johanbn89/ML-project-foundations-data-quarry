# ML Project Foundations – Data Quarry

This repository serves as a **shared data repository** for multiple machine learning projects.
Each ML project should live in its own repository and consume data from this repo in a
controlled and reproducible way.


This repository combines application code (src/), dataset-specific developer utilities (data/\<dataset\>/utils/), and a versioned data registry (data/\<dataset\>/) managed with Git and DVC on a per-dataset basis. Dataset tooling is intentionally split: shared dataset management lives in data/, e.g. data/add_dataset.py, while per-dataset helper scripts live only in data/\<dataset\>/utils/.

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

- The `dvc/` folder is the root for DVC-tracked data. It is not present after a fresh clone and is created on demand by `dvc pull`.

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

Some **components** of the dataset data changed for that version. As a result, all present components receive an additional row with the new dataset tag, even if only a subset of components changed.

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

Used at runtime (training, evaluation, pipelines) to materialize dataset files
for a specific dataset version.

typically used by, 

```python
from data_quarry.tools import get_file_paths
```

Inputs:

- ref — git commit hash or dataset tag (e.g. dataset1-v3)
- dataset — dataset folder name
- components — list of component names (["raw", "target"])

Required environment variables:

- DATA_REPO_ROOT — path to the repo root (where .git and DVC config live)
- DATA_ROOT — path to the data/ directory inside that repo

Behavior:

1. git checkout \<ref\>
2. dvc pull data/\<dataset\>/dvc.dvc
3. Return file paths under:
   data/\<dataset\>/dvc/\<component\>/**

Important:

This function mutates the repository working tree by design.
It should be used in controlled environments (local dev, CI jobs, containers).

---

## Setup

Install dependencies using:
should add remote here???
```bash
uv sync
```

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


## DVC Remote

Data is stored remotely using DVC. This need to be configured to work. 
TODO: Add this when remote is added.
