# data/add_dataset.py
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

# DVC-tracked data lives under data/<dataset>/dvc/<component>
DVC_SUBDIR_NAME = "dvc"

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

| Folder | Description | Schema | Produced by | Tag | Changed |
|---|---|---|---|---|---|
{% if c.history %}
{% for row in c.history %}
| `{{ c.path }}` | {{ c.description or "_…_" }} | {{ ("`" ~ c.schema ~ "`") if c.schema else "_…_" }} | {{ ("`" ~ c.produced_by ~ "`") if c.produced_by else "_…_" }} | `{{ row.tag }}` | `{{ row.changed }}` |
{% endfor %}
{% else %}
| `{{ c.path }}` | {{ c.description or "_…_" }} | {{ ("`" ~ c.schema ~ "`") if c.schema else "_…_" }} | {{ ("`" ~ c.produced_by ~ "`") if c.produced_by else "_…_" }} | `{{ c.tag }}` | `{{ "yes" if c.changed else "no" }}` |
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
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str):
                out[k] = v
        return out
    return {}


def _as_list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            d: Dict[str, Any] = {}
            for k, v in item.items():
                if isinstance(k, str):
                    d[k] = v
            out.append(d)
    return out


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
        if not c2 or c2 in seen:
            continue
        seen.add(c2)
        out.append(c2)
    return out


def _dataset_tag(dataset_name: str, tag_version: int) -> str:
    return f"{dataset_name}-v{tag_version}"


def _ensure_components_structure(meta: Dict[str, Any], dataset_dir: Path, components: List[str]) -> None:
    """
    Ensure YAML has component entries and that DVC directory structure exists.
    Does NOT append version history.
    """
    meta_components = _as_dict(meta.get("components"))
    meta["components"] = meta_components

    keep = set(components)
    for existing in list(meta_components.keys()):
        if existing not in keep:
            del meta_components[existing]

    dvc_root = dataset_dir / DVC_SUBDIR_NAME
    dvc_root.mkdir(parents=True, exist_ok=True)

    for cname in components:
        (dvc_root / cname).mkdir(parents=True, exist_ok=True)

        entry = _as_dict(meta_components.get(cname))
        meta_components[cname] = entry

        entry.setdefault("path", cname)
        entry.setdefault("description", "")
        entry.setdefault("schema", None)
        entry.setdefault("produced_by", None)

        # Versioning fields (dataset-wide)
        entry.setdefault("tag", "")
        entry.setdefault("changed", False)
        entry.setdefault("history", [])


def _update_component_history_on_version(
    meta: Dict[str, Any],
    components: List[str],
    *,
    prev_tag: str,
    new_tag: str,
    changed_any: bool,
) -> None:
    """
    Append a history row for every component for the new dataset version.
    The 'changed' flag is dataset-wide (same for all components).
    """
    meta_components = _as_dict(meta.get("components"))

    for cname in components:
        entry = _as_dict(meta_components.get(cname))
        meta_components[cname] = entry

        history = _as_list_of_dicts(entry.get("history"))
        entry["history"] = history

        # Seed previous version if history is empty so tables grow immediately
        if not history and prev_tag != new_tag:
            history.append({"tag": prev_tag, "changed": "n/a"})

        history.append({"tag": new_tag, "changed": "yes" if changed_any else "no"})

        entry["tag"] = new_tag
        entry["changed"] = changed_any


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
        history_raw = _as_list_of_dicts(raw.get("history"))

        history: List[Dict[str, str]] = []
        for row in history_raw:
            history.append(
                {
                    "tag": str(row.get("tag", "")),
                    "changed": str(row.get("changed", "")),
                }
            )

        safe_components[cname] = {
            "path": str(raw.get("path", cname)),
            "description": str(raw.get("description", "")),
            "schema": raw.get("schema", None),
            "produced_by": raw.get("produced_by", None),
            "tag": str(raw.get("tag", "")),
            "changed": bool(raw.get("changed", False)),
            "history": history,
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
    return path.read_bytes() if path.exists() else b""


def _run_dvc_add(path: Path) -> Tuple[int, str]:
    res = subprocess.run(
        ["dvc", "add", str(path)],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
    )
    out = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
    return res.returncode, out.strip()


def _dvc_file_for_output_dir(output_dir: Path) -> Path:
    # DVC creates "<output_dir>.dvc" next to the output directory
    # e.g. data/dataset1/dvc  ->  data/dataset1/dvc.dvc
    return output_dir.with_suffix(".dvc")


def _dvc_add_dataset(dataset_dir: Path) -> Tuple[bool, Path]:
    """
    DVC-add the dataset's DVC subfolder: data/<dataset>/dvc
    Produces: data/<dataset>/dvc.dvc
    """
    dvc_output_dir = dataset_dir / DVC_SUBDIR_NAME
    dvc_output_dir.mkdir(parents=True, exist_ok=True)

    dvc_file = _dvc_file_for_output_dir(dvc_output_dir)

    before = _read_bytes_if_exists(dvc_file)
    existed_before = dvc_file.exists()

    rc, out = _run_dvc_add(dvc_output_dir)
    if rc != 0:
        if out:
            print(out)
        raise SystemExit(rc)

    after = _read_bytes_if_exists(dvc_file)

    if not existed_before and dvc_file.exists():
        return True, dvc_file
    if before != after:
        return True, dvc_file
    return False, dvc_file


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

    # Ensure structure exists before dvc add
    _ensure_components_structure(meta, dataset_dir, components)

    # DVC add dataset-level output: data/<dataset>/dvc
    changed_any, dvc_file = _dvc_add_dataset(dataset_dir)
    dvc_rel = dvc_file.relative_to(REPO_ROOT)
    if changed_any:
        print(f"[updated] {dvc_rel} changed")
    else:
        print(f"[nochange] {dvc_rel} unchanged")

    # Bump dataset version only when DVC output changed
    if changed_any:
        tag_version += 1
        meta["tag_version"] = tag_version
        print(f"[tag] data changed -> bump tag_version to v{tag_version}")
    else:
        meta["tag_version"] = tag_version
        print(f"[tag] no data change -> keep tag_version at v{tag_version}")

    prev_tag = _dataset_tag(args.name, prev_tag_version)
    new_tag = _dataset_tag(args.name, tag_version)

    # Append one row per version for each component, with dataset-wide changed flag
    _update_component_history_on_version(
        meta,
        components,
        prev_tag=prev_tag,
        new_tag=new_tag,
        changed_any=changed_any,
    )

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
    print(f"  git add {dvc_rel}")
    print(f"  git add {dataset_dir.relative_to(REPO_ROOT)}/.gitignore")
    print(f'  git commit -m "Add/update dataset {args.name}"')
    if changed_any:
        print(f"  git tag {new_tag}")
        print(f"  # optionally push tag: git push origin {new_tag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
