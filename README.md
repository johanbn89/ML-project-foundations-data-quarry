# ML Project Foundations – Data Quarry

This repository serves as a **shared data repository** for multiple machine learning projects.
Each ML project should live in its own repository and consume data from this repo in a
controlled and reproducible way.

The goal is to:
- Centralize dataset storage
- Enable reproducible experiments
- Avoid duplicating large datasets across projects

---

## Data Versioning

We use **DVC (Data Version Control)** for dataset versioning and storage.

DVC allows us to:
- Track large datasets without committing them to Git
- Version datasets alongside code using Git tags/commits
- Store data remotely (e.g. S3, GCS, Azure Blob, etc.)
- Pull only the data needed for a specific project or experiment

> **Note:** DVC tracks data via `.dvc` files and a remote storage backend. The actual data
> is not stored in Git.

---

## Setup

Install dependencies using:

```bash
uv sync
```

## Pulling Data

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

## Dataset Versioning Strategy

Datasets are versioned using Git commits or tags in combination with DVC.

A typical workflow:

Check out the Git commit or tag corresponding to the desired dataset version

Pull the required data using DVC

```bash
git checkout <tag-or-commit>
dvc pull data/<dataset_name>
```

## Repository Structure

Each dataset lives in its own directory under data/.

data/
  cats/
    cats.dvc
    utils/
      preprocess.py
      transform.py
    raw/
      file1
      ...
      fileN
    processed/
      file1
      ...
      fileN

  dogs/
    dogs.dvc
    utils/
      preprocess.py
      transform.py
    raw/
      file1
      ...
      fileN
    processed/
      file1
      ...
      fileN

## Directory Conventions

raw/
Immutable raw input data. Never modify files in this directory.

processed/
Cleaned, transformed, or feature-engineered data derived from raw/.

utils/
Dataset-specific scripts for preprocessing and transformations.

<dataset>.dvc
DVC tracking file for the dataset.

Open Questions / Future Improvements

Should we provide a small CLI or Python interface around DVC?
Example:

```code
get_data_by_tag(tag, dataset):
    git checkout tag
    dvc pull data/<dataset>
```

How strictly should preprocessing logic live in this repo vs. project-specific repos?

## Thoughts on structure & technical choices

### 👍 What’s good

- **Clear separation** between:
  - data repository
  - ML project repositories
- **One dataset per folder** → very scalable
- Using **DVC correctly** for large data
- `raw / processed` split is a strong convention

### ⚠️ Technical corrections / clarifications

1. **“Repo for handling of data” → “Shared data repository”**  
   Clearer and more professional phrasing.

2. **DVC explanation**
   - Avoid vague phrasing like *“short explanation”*
   - README should explain *why* DVC is used, not how it works internally.

3. **`.dvc` file naming**
   - Prefer explicit naming (`cats.dvc`) instead of a generic `.dvc`
   - This makes it easier to understand what is tracked.

4. **Scripts naming**
   - Use `preprocess.py` instead of `pre-process.py`
   - Hyphens are awkward in imports and tooling.

---

## 3. Suggestions for extensions / additions

These are optional, but I’d strongly consider them.

### A. Add a **Data Contract section**

Describe expectations for datasets:

## Data Contract

Each dataset should:
- Have immutable raw data
- Document schema, labels, and assumptions
- Avoid breaking changes without a new version
You could even require a README.md per dataset.

B. Add a Remote Storage section

## DVC Remote

Data is stored remotely using DVC.
The configured remote is intentionally not documented here.
Contact the project maintainers if you need access.
(This avoids leaking infra details.)

C. Add a Reproducibility section
This is very valuable for ML teams:

## Reproducibility

To reproduce an experiment:
1. Check out the Git commit or tag used by the project
2. Pull the required datasets with DVC
3. Run the project pipeline


D. About the “DVC interface” idea
My recommendation:
❌ Don’t wrap DVC too early.

Reasons:

DVC already is the interface

Wrappers often hide important behavior

Git + DVC is a well-understood mental model

If you do add something later:

Make it a thin helper script

Do not abstract away Git/DVC concepts

Prefer CLI over Python API
