"""
We should create or fill out dataset readme and table of datasets, link to dataset readme.

dataset readme should contain
- tag
- Information about data, eg.,
  where it comes from and it have been derived from -TRANSFORMS-> to
  A section of this for each component eg. raw, target, features, splits, etc.

Pipeline of actions,
 - Developer have added some folder with data or changed files in
   data/<dataset_name>/componentXX, data/<dataset_name>/componentYY, etc.
 - We want to track this, so we run `add_dataset.py` script
    - This script will create or update data/<dataset_name>/README.md
    - This script will create or update data/datasets.md (table of datasets)
    - dvc add data/<dataset_name>/** (maybe optional, or we do it always?)
    - git add data/<dataset_name>/README.md data/datasets.md data/<dataset_name>/**.dvc
    - git commit -m "Add/update dataset <dataset_name>"
    - git push origin main

Dataset helper (local dev tool).

Dev deps:
  uv add --dev pyyaml jinja2 types-PyYAML

Examples:
  uv run python data/add_dataset.py --name dataset1 --tag mytag --version 111.1.0 --components raw target
  uv run python data/add_dataset.py --name dataset1 --tag mytag --version 111.1.0 --components raw target --dvc
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

import yaml
from jinja2 import Environment, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DATASETS_MD = DATA_DIR / "datasets.md"


README_TEMPLATE = r"""# Dataset: `{{ name }}`

{% if description -%}
{{ description }}
{%- else -%}
_Describe what this dataset is and what it’s for._
{%- endif %}

## Components
{%- if components %}

{%- for cname in components_order %}
{%- set c = components[cname] %}

### `{{ cname }}`

| Folder | Description | Schema | Produced by | Tag |
|---|---|---|---|---|
| `{{ c.path }}` | {{ c.description or "_…_" }} | {{ ("`" ~ c.schema ~ "`") if c.schema else "_…_" }} | {{ ("`" ~ c.produced_by ~ "`") if c.produced_by else "_…_" }} | `{{ c.tag }}` |


{%- endfor %}

{%- else %}

_No components registered. Re-run with `--components raw target ...`._

{%- endif %}
"""


DATASETS_TEMPLATE = """# Datasets

This file is maintained by `data/add_dataset.py`.

| Dataset | Tag | Version | Status | Components |
|---|---|---|---|---:|
{% for d in datasets %}
| [`{{ d.name }}`]({{ d.rel_dir }}/) | `{{ d.tag }}` | `{{ d.version }}` | `{{ d.status }}` | {{ d.n_components }} |
{% endfor %}
"""


def _env() -> Environment:
    return Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)


def _as_dict(value: Any) -> Dict[str, Any]:
    """
    Normalize a YAML-loaded value to a dict[str, Any].
    """
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str):
                out[k] = v
        return out
    return {}


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _as_dict(loaded)


def _write_yaml(path: Path, data: Mapping[str, Any], *, dry_run: bool) -> None:
    txt = yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True)
    if dry_run:
        print(f"[dry-run] write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(txt, encoding="utf-8")


def _write_text(path: Path, content: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _normalize_components(components: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for c in components:
        c2 = str(c).strip().strip("/\\")
        if not c2:
            continue
        if c2 in seen:
            continue
        seen.add(c2)
        out.append(c2)
    return out


def _ensure_components(meta: Dict[str, Any], dataset_dir: Path, components: List[str]) -> None:
    meta_components = _as_dict(meta.get("components"))
    meta["components"] = meta_components

    # Make YAML components exactly match explicit list
    keep = set(components)
    for existing in list(meta_components.keys()):
        if existing not in keep:
            del meta_components[existing]

    for cname in components:
        (dataset_dir / cname).mkdir(parents=True, exist_ok=True)

        raw_entry = meta_components.get(cname)
        entry = _as_dict(raw_entry)
        meta_components[cname] = entry

        entry.setdefault("path", cname)
        entry.setdefault("description", "")
        entry.setdefault("schema", None)
        entry.setdefault("produced_by", None)
        entry.setdefault("tag", "")  # per-component tag


def _render_readme(meta: Dict[str, Any]) -> str:
    env = _env()
    tmpl = env.from_string(README_TEMPLATE)

    name = str(meta.get("name", ""))
    description = str(meta.get("description", "") or "")

    components = _as_dict(meta.get("components"))
    components_order = sorted(components.keys())

    # Ensure each comp has expected keys (for StrictUndefined)
    safe_components: Dict[str, Dict[str, Any]] = {}
    for cname in components_order:
        raw = _as_dict(components.get(cname))
        safe_components[cname] = {
            "path": raw.get("path", cname),
            "description": raw.get("description", ""),
            "schema": raw.get("schema", None),
            "produced_by": raw.get("produced_by", None),
            "tag": raw.get("tag", ""),
        }

    return (
        tmpl.render(
            name=name,
            description=description,
            components=safe_components,
            components_order=components_order,
        ).rstrip()
        + "\n"
    )


def _render_datasets_md(all_meta: List[Dict[str, Any]]) -> str:
    env = _env()
    tmpl = env.from_string(DATASETS_TEMPLATE)

    rows: List[Dict[str, Any]] = []
    for m in sorted(all_meta, key=lambda x: str(x.get("name", "")).lower()):
        name = str(m.get("name", ""))
        ds_dir = DATA_DIR / name

        # datasets.md lives in data/, so links should be relative to DATA_DIR
        rel_dir = ds_dir.relative_to(DATA_DIR).as_posix()
        rel_readme = (ds_dir / "README.md").relative_to(DATA_DIR).as_posix()

        comps = _as_dict(m.get("components"))

        rows.append(
            {
                "name": name,
                "tag": str(m.get("tag", "")),
                "version": str(m.get("version", "")),
                "status": str(m.get("status", "")),
                "n_components": len(comps),
                "rel_dir": rel_dir,
                "rel_readme": rel_readme,
            }
        )

    return tmpl.render(datasets=rows).rstrip() + "\n"


def _find_all_dataset_meta() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not DATA_DIR.exists():
        return out

    for p in sorted(DATA_DIR.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        meta_path = p / "dataset.yaml"
        if not meta_path.exists():
            continue
        meta = _read_yaml(meta_path)
        if meta.get("name"):
            out.append(meta)
    return out


def _run_dvc_add(path: Path, *, dry_run: bool) -> int:
    if dry_run:
        print(f"[dry-run] dvc add {path}")
        return 0
    print(f"[run] dvc add {path}")
    res = subprocess.run(
        ["dvc", "add", str(path)],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
    )
    if res.returncode != 0:
        msg = (res.stderr or "").strip() or (res.stdout or "").strip()
        if msg:
            print(msg)
    return res.returncode


def main() -> int:
    p = argparse.ArgumentParser(description="Create/update dataset.yaml + README + datasets.md (explicit components).")
    p.add_argument("--name", required=True, help="Dataset folder name under data/ (e.g. dataset1)")
    p.add_argument("--tag", required=True, help="Dataset tag (dataset-level, used in datasets.md)")
    p.add_argument("--version", required=True, help="Dataset version (used in datasets.md)")
    p.add_argument("--status", default="draft", choices=["draft", "active", "deprecated"])
    p.add_argument("--description", default="", help="Dataset description shown in README (optional).")

    p.add_argument(
        "--components",
        nargs="+",
        required=True,
        help="Explicit component subfolders, e.g. --components raw target features",
    )
    p.add_argument("--dvc", action="store_true", help="Run `dvc add` for the explicit components only.")
    p.add_argument("--dry-run", action="store_true")

    args = p.parse_args()

    components = _normalize_components(args.components)

    dataset_dir = DATA_DIR / args.name
    dataset_dir.mkdir(parents=True, exist_ok=True)

    today = dt.date.today().isoformat()
    meta_path = dataset_dir / "dataset.yaml"

    meta = _read_yaml(meta_path)
    meta.setdefault("created", today)
    meta["updated"] = today

    meta["name"] = args.name
    meta["tag"] = args.tag
    meta["version"] = args.version
    meta["status"] = args.status

    if args.description:
        meta["description"] = args.description
    else:
        meta.setdefault("description", "")

    _ensure_components(meta, dataset_dir, components)

    _write_yaml(meta_path, meta, dry_run=args.dry_run)
    print(f"Updated {meta_path.relative_to(REPO_ROOT)}")

    readme_path = dataset_dir / "README.md"
    readme_txt = _render_readme(meta)
    _write_text(readme_path, readme_txt, dry_run=args.dry_run)
    print(f"Updated {readme_path.relative_to(REPO_ROOT)}")

    all_meta = _find_all_dataset_meta()
    if not any(m.get("name") == args.name for m in all_meta):
        all_meta.append(meta)

    datasets_txt = _render_datasets_md(all_meta)
    _write_text(DATASETS_MD, datasets_txt, dry_run=args.dry_run)
    print(f"Updated {DATASETS_MD.relative_to(REPO_ROOT)}")

    if args.dvc:
        for cname in components:
            dvc_file = dataset_dir / f"{cname}.dvc"
            if dvc_file.exists():
                print(f"[skip] {cname} already tracked ({dvc_file.name})")
                continue
            rc = _run_dvc_add(dataset_dir / cname, dry_run=args.dry_run)
            if rc != 0:
                return rc

    print("\nNext:")
    print(
        f"  git add {meta_path.relative_to(REPO_ROOT)} {readme_path.relative_to(REPO_ROOT)} {DATASETS_MD.relative_to(REPO_ROOT)}"
    )
    if args.dvc:
        print("  git add *.dvc")
        print(f"  git add {dataset_dir.relative_to(REPO_ROOT)}/.gitignore")
    print(f'  git commit -m "Add/update dataset {args.name}"')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
