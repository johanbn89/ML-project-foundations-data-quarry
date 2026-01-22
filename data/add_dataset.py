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
    - This script will create or update data/README.md (table of datasets)
    - dvc add data/<dataset_name>/** (maybe optional, or we do it always?)
    - git add data/<dataset_name>/README.md data/README.md data/<dataset_name>/**.dvc
    - git commit -m "Add/update dataset <dataset_name>"
    - git push origin main

Dataset helper (local dev tool).

Dev deps:
  uv add --dev pyyaml jinja2 types-PyYAML

Examples:
  uv run python data/add_dataset.py --name dataset1 --components raw target
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import yaml
from jinja2 import Environment, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DATA_INDEX_MD = DATA_DIR / "README.md"


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
{% if c.tags %}
{% for t in c.tags %}
| `{{ c.path }}` | {{ c.description or "_…_" }} | {{ ("`" ~ c.schema ~ "`") if c.schema else "_…_" }} | {{ ("`" ~ c.produced_by ~ "`") if c.produced_by else "_…_" }} | `{{ t }}` |
{% endfor %}
{% else %}
| `{{ c.path }}` | {{ c.description or "_…_" }} | {{ ("`" ~ c.schema ~ "`") if c.schema else "_…_" }} | {{ ("`" ~ c.produced_by ~ "`") if c.produced_by else "_…_" }} | `{{ c.tag }}` |
{% endif %}

{%- endfor %}

{%- else %}

_No components registered. Re-run with `--components raw target ...`._

{%- endif %}
"""


DATA_INDEX_TEMPLATE = """# Datasets

This file is maintained by `data/add_dataset.py`.

| Dataset | Status | Components |
|---|---|---:|
{% for d in datasets %}
| [`{{ d.name }}`]({{ d.rel_dir }}/) | `{{ d.status }}` | {{ d.n_components }} |
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


def _write_yaml(path: Path, data: Mapping[str, Any]) -> None:
    txt = yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(txt, encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
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


def _component_tag(dataset_name: str, component_name: str, tag_version: int) -> str:
    return f"{dataset_name}-{component_name}-v{tag_version}"


def _ensure_components(
    meta: Dict[str, Any],
    dataset_dir: Path,
    components: List[str],
    *,
    prev_tag_version: int,
    tag_version: int,
    changed_any: bool,
) -> None:
    meta_components = _as_dict(meta.get("components"))
    meta["components"] = meta_components

    # Make YAML components exactly match explicit list
    keep = set(components)
    for existing in list(meta_components.keys()):
        if existing not in keep:
            del meta_components[existing]

    dataset_name = str(meta.get("name", "") or "")

    for cname in components:
        (dataset_dir / cname).mkdir(parents=True, exist_ok=True)

        raw_entry = meta_components.get(cname)
        entry = _as_dict(raw_entry)
        meta_components[cname] = entry

        entry.setdefault("path", cname)
        entry.setdefault("description", "")
        entry.setdefault("schema", None)
        entry.setdefault("produced_by", None)

        new_tag = _component_tag(dataset_name, cname, tag_version)
        prev_tag = _component_tag(dataset_name, cname, prev_tag_version)

        tags_val = entry.get("tags", [])
        tags: List[str] = tags_val if isinstance(tags_val, list) else []
        tags = [str(t) for t in tags if str(t)]

        # Seed history on first bump so README grows immediately:
        # if we are bumping and there's no history yet, add previous version tag first.
        if changed_any:
            if not tags and prev_tag_version >= 0 and prev_tag != new_tag:
                tags.append(prev_tag)
            if not tags or tags[-1] != new_tag:
                tags.append(new_tag)

        entry["tags"] = tags
        entry["tag"] = tags[-1] if tags else new_tag


def _render_readme(meta: Dict[str, Any]) -> str:
    env = _env()
    tmpl = env.from_string(README_TEMPLATE)

    name = str(meta.get("name", ""))
    description = str(meta.get("description", "") or "")

    components = _as_dict(meta.get("components"))
    components_order = sorted(components.keys())

    safe_components: Dict[str, Dict[str, Any]] = {}
    for cname in components_order:
        raw = _as_dict(components.get(cname))
        tags_val = raw.get("tags", [])
        tags = [str(t) for t in tags_val] if isinstance(tags_val, list) else []

        safe_components[cname] = {
            "path": raw.get("path", cname),
            "description": raw.get("description", ""),
            "schema": raw.get("schema", None),
            "produced_by": raw.get("produced_by", None),
            "tag": raw.get("tag", ""),
            "tags": tags,
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


def _render_data_index(all_meta: List[Dict[str, Any]]) -> str:
    env = _env()
    tmpl = env.from_string(DATA_INDEX_TEMPLATE)

    rows: List[Dict[str, Any]] = []
    for m in sorted(all_meta, key=lambda x: str(x.get("name", "")).lower()):
        name = str(m.get("name", ""))
        ds_dir = DATA_DIR / name
        rel_dir = ds_dir.relative_to(DATA_DIR).as_posix()
        comps = _as_dict(m.get("components"))

        rows.append(
            {
                "name": name,
                "status": str(m.get("status", "")),
                "n_components": len(comps),
                "rel_dir": rel_dir,
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


def _read_bytes_if_exists(path: Path) -> bytes:
    if not path.exists():
        return b""
    return path.read_bytes()


def _run_dvc_add(component_path: Path) -> Tuple[int, str]:
    """
    Run `dvc add <component_path>` and return (exit_code, combined_output).
    """
    res = subprocess.run(
        ["dvc", "add", str(component_path)],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
    )
    out = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
    return res.returncode, out.strip()


def _dvc_add_components(dataset_dir: Path, components: List[str]) -> Tuple[bool, List[str]]:
    """
    Always DVC-add each component folder.
    Returns:
      changed_any: True if any *.dvc file changed or was created
      messages: human-friendly status lines
    """
    changed_any = False
    messages: List[str] = []

    for cname in components:
        comp_path = dataset_dir / cname
        dvc_file = dataset_dir / f"{cname}.dvc"

        before = _read_bytes_if_exists(dvc_file)
        existed_before = dvc_file.exists()

        rc, out = _run_dvc_add(comp_path)
        if rc != 0:
            if out:
                print(out)
            raise SystemExit(rc)

        after = _read_bytes_if_exists(dvc_file)

        if not existed_before and dvc_file.exists():
            changed_any = True
            messages.append(f"[new] {cname}.dvc created")
        elif before != after:
            changed_any = True
            messages.append(f"[updated] {cname}.dvc changed")
        else:
            messages.append(f"[nochange] {cname}.dvc unchanged")

    return changed_any, messages


def main() -> int:
    p = argparse.ArgumentParser(
        description="Create/update dataset.yaml + README + data/README.md (explicit components)."
    )
    p.add_argument("--name", required=True, help="Dataset folder name under data/ (e.g. dataset1)")
    p.add_argument("--status", default="draft", choices=["draft", "active", "deprecated"])
    p.add_argument("--description", default="", help="Dataset description shown in README (optional).")
    p.add_argument(
        "--components",
        nargs="+",
        required=True,
        help="Explicit component subfolders, e.g. --components raw target features",
    )
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
    meta["status"] = args.status

    if args.description:
        meta["description"] = args.description
    else:
        meta.setdefault("description", "")

    raw_tag_version = meta.get("tag_version", 0)
    tag_version = int(raw_tag_version) if isinstance(raw_tag_version, int) else 0
    prev_tag_version = tag_version

    # 1) Always DVC add, and detect if anything changed
    changed_any, msgs = _dvc_add_components(dataset_dir, components)
    for m in msgs:
        print(m)

    # 2) Bump tag_version only on change
    if changed_any:
        tag_version += 1
        meta["tag_version"] = tag_version
        print(f"[tag] data changed -> bump tag_version to v{tag_version}")
    else:
        meta["tag_version"] = tag_version
        print(f"[tag] no data change -> keep tag_version at v{tag_version}")

    # 3) Ensure YAML component entries + derived tags (and tag history)
    _ensure_components(
        meta,
        dataset_dir,
        components,
        prev_tag_version=prev_tag_version,
        tag_version=tag_version,
        changed_any=changed_any,
    )

    # 4) Write dataset.yaml, README.md, and data/README.md index
    _write_yaml(meta_path, meta)
    print(f"Updated {meta_path.relative_to(REPO_ROOT)}")

    readme_path = dataset_dir / "README.md"
    _write_text(readme_path, _render_readme(meta))
    print(f"Updated {readme_path.relative_to(REPO_ROOT)}")

    all_meta = _find_all_dataset_meta()
    if not any(m.get("name") == args.name for m in all_meta):
        all_meta.append(meta)

    _write_text(DATA_INDEX_MD, _render_data_index(all_meta))
    print(f"Updated {DATA_INDEX_MD.relative_to(REPO_ROOT)}")

    print("\nNext:")
    print(
        f"  git add {meta_path.relative_to(REPO_ROOT)} {readme_path.relative_to(REPO_ROOT)} {DATA_INDEX_MD.relative_to(REPO_ROOT)}"
    )
    print("  git add *.dvc")
    print(f"  git add {dataset_dir.relative_to(REPO_ROOT)}/.gitignore")
    print(f'  git commit -m "Add/update dataset {args.name}"')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
