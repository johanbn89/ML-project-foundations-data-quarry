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

This is a local developer tool, not part of the package. And can be runned like:
uv run python data/add_dataset.py --name <dataset_name> --tag <tag> --version <version>
or should we have tag and version derived from git tags or similar?

Local developer tool (not part of the package).

Creates/updates:
- data/<dataset_name>/dataset.yaml  (single source of truth metadata)
- data/<dataset_name>/README.md     (generated blocks + freeform outside markers)
- data/datasets.md                 (table generated from dataset.yaml files)

Explicit components (recommended):
  uv run python data/add_dataset.py --name dataset1 --tag mytag --version 0.1.0 --components raw target --dvc

Notes:
- This script will NOT auto-discover components from folders.
- Only components passed via --components are treated as dataset data components.
- If --dvc is set, it only DVC-adds those explicit components.
- Non-component folders (e.g. utils/) are ignored unless explicitly listed.


Local developer tool (not part of the package).

Creates/updates:
- data/<dataset_name>/dataset.yaml  (single source of truth metadata)
- data/<dataset_name>/README.md     (generated blocks + freeform outside markers)
- data/datasets.md                 (table generated from dataset.yaml files)

Explicit components (recommended):
  uv run python data/add_dataset.py --name dataset1 --tag mytag --version 0.1.0 --components raw target --dvc

Notes:
- This script will NOT auto-discover components from folders.
- Only components passed via --components are treated as dataset data components.
- If --dvc is set, it only DVC-adds those explicit components.
- Non-component folders (e.g. utils/) are ignored unless explicitly listed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

# Repo layout
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DATASETS_INDEX = DATA_DIR / "README.md"

# Markers for idempotent README/index updates
README_MARK_META_START = "<!-- dataset-metadata:start -->"
README_MARK_META_END = "<!-- dataset-metadata:end -->"
README_MARK_COMPONENTS_START = "<!-- dataset-components:start -->"
README_MARK_COMPONENTS_END = "<!-- dataset-components:end -->"

INDEX_MARK_TABLE_START = "<!-- datasets-table:start -->"
INDEX_MARK_TABLE_END = "<!-- datasets-table:end -->"


# -----------------------------
# Minimal YAML (no dependencies)
# -----------------------------
# Subset loader/dumper adequate for YAML this tool emits.
# If your team edits YAML freely, consider adding PyYAML.
def _yaml_dump(obj: Any, indent: int = 0) -> str:
    sp = "  " * indent
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, (int, float)):
        return str(obj)
    if isinstance(obj, str):
        # Quote only when needed
        if obj == "" or any(c in obj for c in [":", "#", "{", "}", "[", "]", "\n", '"', "'"]):
            return '"' + obj.replace('"', '\\"') + '"'
        return obj
    if isinstance(obj, list):
        if not obj:
            return "[]"
        list_lines: List[str] = []
        for item in obj:
            if isinstance(item, (dict, list)):
                list_lines.append(f"{sp}- {_yaml_dump(item, indent + 1).lstrip()}")
            else:
                list_lines.append(f"{sp}- {_yaml_dump(item, 0)}")
        return "\n".join(list_lines)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        dict_lines: List[str] = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                dict_lines.append(f"{sp}{k}:")
                dict_lines.append(_yaml_dump(v, indent + 1))
            else:
                dict_lines.append(f"{sp}{k}: {_yaml_dump(v, 0)}")
        return "\n".join(dict_lines)
    raise TypeError(f"Unsupported type for yaml dump: {type(obj)}")


def _yaml_load(text: str) -> Dict[str, Any]:
    if not text.strip():
        return {}

    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    i = 0

    def current_indent(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    def parse_scalar(s: str) -> Any:
        if s in ("null", "Null", "NULL"):
            return None
        if s in ("true", "True", "TRUE"):
            return True
        if s in ("false", "False", "FALSE"):
            return False
        if re.fullmatch(r"-?\d+", s):
            try:
                return int(s)
            except ValueError:
                pass
        if re.fullmatch(r"-?\d+\.\d+", s):
            try:
                return float(s)
            except ValueError:
                pass
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            q = s[0]
            inner = s[1:-1]
            if q == '"':
                inner = inner.replace('\\"', '"')
            return inner
        return s

    def parse_block(base_indent: int) -> Any:
        nonlocal i
        mapping: Dict[str, Any] = {}
        sequence_items: List[Any] = []
        mode: Optional[str] = None  # "map" | "seq"

        while i < len(lines):
            line = lines[i]
            if not line.strip() or line.strip().startswith("#"):
                i += 1
                continue

            ind = current_indent(line)
            if ind < base_indent:
                break
            if ind > base_indent:
                # unexpected in our emitted subset; stop block
                break

            s = line.strip()

            if s.startswith("- "):
                if mode is None:
                    mode = "seq"
                if mode != "seq":
                    break

                item_str = s[2:].strip()
                i += 1

                if item_str == "":
                    sequence_items.append(parse_block(base_indent + 2))
                    continue

                if ":" in item_str and not item_str.startswith('"'):
                    # inline dict like "- key: value"
                    k, v = item_str.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    item_map: Dict[str, Any] = {}
                    if v == "":
                        item_map[k] = parse_block(base_indent + 4)
                    else:
                        item_map[k] = parse_scalar(v)

                    # merge subsequent indented keys
                    if i < len(lines) and current_indent(lines[i]) >= base_indent + 2:
                        extra = parse_block(base_indent + 2)
                        if isinstance(extra, dict):
                            item_map.update(extra)
                    sequence_items.append(item_map)
                else:
                    sequence_items.append(parse_scalar(item_str))
            else:
                if mode is None:
                    mode = "map"
                if mode != "map":
                    break

                if ":" not in s:
                    break
                k, v = s.split(":", 1)
                key = k.strip()
                val = v.strip()
                i += 1
                if val == "":
                    mapping[key] = parse_block(base_indent + 2)
                else:
                    mapping[key] = parse_scalar(val)

        return sequence_items if mode == "seq" else mapping

    parsed = parse_block(0)
    if not isinstance(parsed, dict):
        raise ValueError("Top-level YAML must be a mapping for this tool.")
    return parsed


# -----------------------------
# IO helpers
# -----------------------------
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _write_text(path: Path, content: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _replace_block(original: str, *, start_marker: str, end_marker: str, new_body: str) -> str:
    if not new_body.endswith("\n"):
        new_body += "\n"
    block = f"{start_marker}\n{new_body}{end_marker}"
    pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), flags=re.DOTALL)
    if pattern.search(original):
        return pattern.sub(block, original, count=1)

    # Insert after first H1 if present, else prepend.
    lines = original.splitlines(True)
    insert_at = 0
    for idx, line in enumerate(lines[:30]):
        if line.startswith("# "):
            insert_at = idx + 1
            if insert_at < len(lines) and lines[insert_at].strip() == "":
                insert_at += 1
            break

    prefix = "".join(lines[:insert_at])
    suffix = "".join(lines[insert_at:])
    spacer = "" if insert_at == 0 else "\n"
    return prefix + spacer + block + "\n\n" + suffix


# -----------------------------
# Dataset metadata helpers
# -----------------------------
def _dataset_yaml_path(dataset_dir: Path) -> Path:
    return dataset_dir / "dataset.yaml"


def _load_dataset_yaml(path: Path) -> Dict[str, Any]:
    txt = _read_text(path)
    return _yaml_load(txt) if txt.strip() else {}


def _save_dataset_yaml(path: Path, data: Dict[str, Any], *, dry_run: bool) -> None:
    preferred_order = [
        "name",
        "tag",
        "version",
        "status",
        "owner",
        "license",
        "created",
        "updated",
        "description",
        "lineage",
        "components",
        "splits",
        "notes",
    ]
    ordered: Dict[str, Any] = {}
    for k in preferred_order:
        if k in data:
            ordered[k] = data[k]
    for k in data.keys():
        if k not in ordered:
            ordered[k] = data[k]

    content = _yaml_dump(ordered).rstrip() + "\n"
    _write_text(path, content, dry_run=dry_run)


def _normalize_component_names(component_names: Sequence[str]) -> List[str]:
    # Keep order but remove duplicates, strip slashes
    normalized: List[str] = []
    seen: Set[str] = set()
    for c in component_names:
        c2 = str(c).strip().strip("/\\")
        if not c2:
            continue
        if c2 in seen:
            continue
        seen.add(c2)
        normalized.append(c2)
    return normalized


def _ensure_explicit_component_entries(
    meta: Dict[str, Any],
    dataset_dir: Path,
    component_names: Sequence[str],
    *,
    prune_to_explicit: bool,
) -> None:
    """
    - Ensures folders exist for each explicit component
    - Ensures YAML has entries for each explicit component
    - Optionally prunes YAML components to exactly the explicit set
    """
    normalized = _normalize_component_names(component_names)

    meta_components = meta.get("components")
    if not isinstance(meta_components, dict):
        meta_components = {}
        meta["components"] = meta_components

    comp_map: Dict[str, Any] = meta_components

    if prune_to_explicit:
        keep = set(normalized)
        for k in list(comp_map.keys()):
            if k not in keep:
                del comp_map[k]

    for c in normalized:
        (dataset_dir / c).mkdir(parents=True, exist_ok=True)
        entry = comp_map.get(c)
        if not isinstance(entry, dict):
            entry = {}
            comp_map[c] = entry
        entry.setdefault("path", c)
        entry.setdefault("description", "")
        entry.setdefault("schema", None)
        entry.setdefault("produced_by", None)


def _make_readme_from_yaml(meta: Dict[str, Any], dataset_dir: Path, existing: str) -> str:
    name = meta.get("name", dataset_dir.name)
    if not existing.strip():
        existing = f"# Dataset: `{name}`\n\n"

    lineage = meta.get("lineage") or {}
    sources = (lineage.get("sources") or []) if isinstance(lineage, dict) else []
    transforms = (lineage.get("transforms") or []) if isinstance(lineage, dict) else []

    meta_lines = [
        f"- **Name:** `{meta.get('name', name)}`",
        f"- **Tag:** `{meta.get('tag', '')}`",
        f"- **Version:** `{meta.get('version', '')}`",
        f"- **Status:** `{meta.get('status', '')}`",
        f"- **Owner:** `{meta.get('owner', '')}`",
        f"- **License:** `{meta.get('license', '')}`",
        f"- **Created:** `{meta.get('created', '')}`",
        f"- **Updated:** `{meta.get('updated', '')}`",
        f"- **Path:** `{dataset_dir.relative_to(REPO_ROOT).as_posix()}`",
        "",
        "## Description",
        "",
        (meta.get("description") or "_Describe what this dataset is and what it’s for._"),
        "",
        "## Lineage",
        "",
        "### Sources",
    ]

    if sources:
        for s in sources:
            if isinstance(s, dict):
                meta_lines.append(
                    f"- **{s.get('name', '(unnamed)')}** — `{s.get('uri', '')}` (accessed: `{s.get('accessed', '')}`)"
                )
            else:
                meta_lines.append(f"- {s}")
    else:
        meta_lines.append("- _Add sources in `dataset.yaml` under `lineage.sources`._")

    meta_lines += ["", "### Transforms"]
    if transforms:
        for t in transforms:
            if isinstance(t, dict):
                notes = t.get("notes")
                suffix = f" — {notes}" if notes else ""
                meta_lines.append(f"- **{t.get('name', '(unnamed)')}** — `{t.get('uri', '')}`{suffix}")
            else:
                meta_lines.append(f"- {t}")
    else:
        meta_lines.append("- _Add transforms in `dataset.yaml` under `lineage.transforms`._")

    comp_lines = ["## Components", ""]
    components = meta.get("components") or {}

    if isinstance(components, dict) and components:
        for cname in sorted(components.keys()):
            c = components[cname] if isinstance(components[cname], dict) else {}
            comp_lines += [
                f"### `{cname}`",
                "",
                f"- **Path:** `{c.get('path', cname)}`",
                f"- **Description:** {c.get('description', '') or '_…_'}",
                f"- **Schema:** `{c.get('schema')}`" if c.get("schema") else "- **Schema:** _…_",
                f"- **Produced by:** `{c.get('produced_by')}`" if c.get("produced_by") else "- **Produced by:** _…_",
                "",
            ]
    else:
        comp_lines += [
            "_No components registered. Re-run with `--components raw target ...`._",
            "",
        ]

    out_text = existing
    out_text = _replace_block(
        out_text,
        start_marker=README_MARK_META_START,
        end_marker=README_MARK_META_END,
        new_body="\n".join(meta_lines),
    )
    out_text = _replace_block(
        out_text,
        start_marker=README_MARK_COMPONENTS_START,
        end_marker=README_MARK_COMPONENTS_END,
        new_body="\n".join(comp_lines),
    )

    if not out_text.lstrip().startswith("# "):
        out_text = f"# Dataset: `{name}`\n\n" + out_text

    return out_text.rstrip() + "\n"


def _find_all_dataset_yamls() -> List[Path]:
    if not DATA_DIR.exists():
        return []
    yamls: List[Path] = []
    for p in sorted(DATA_DIR.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        y = _dataset_yaml_path(p)
        if y.exists():
            yamls.append(y)
    return yamls


def _make_index_table(all_meta: List[Dict[str, Any]]) -> str:
    header = "| Dataset | Tag | Version | Status | Components | README |\n|---|---|---|---|---:|---|\n"
    lines: List[str] = [header]
    for m in sorted(all_meta, key=lambda x: str(x.get("name", "")).lower()):
        name = str(m.get("name", ""))
        tag = str(m.get("tag", ""))
        version = str(m.get("version", ""))
        status = str(m.get("status", ""))
        comps = m.get("components") or {}
        ncomps = len(comps) if isinstance(comps, dict) else 0

        ds_dir = DATA_DIR / name
        ds_rel = ds_dir.relative_to(DATA_DIR).as_posix()
        readme_rel = (ds_dir / "README.md").relative_to(DATA_DIR).as_posix()
        ds_link = f"[`{name}`]({ds_rel}/)"
        readme_link = f"[README]({readme_rel})"
        lines.append(f"| {ds_link} | `{tag}` | `{version}` | `{status}` | {ncomps} | {readme_link} |\n")
    return "".join(lines)


def _update_datasets_md(all_meta: List[Dict[str, Any]], *, dry_run: bool) -> None:
    existing = _read_text(DATASETS_INDEX)
    if not existing.strip():
        existing = (
            "# Datasets\n\n"
            "This file is maintained by `data/add_dataset.py`.\n\n"
            f"{INDEX_MARK_TABLE_START}\n{INDEX_MARK_TABLE_END}\n"
        )
    table = _make_index_table(all_meta).rstrip("\n")
    updated = _replace_block(
        existing, start_marker=INDEX_MARK_TABLE_START, end_marker=INDEX_MARK_TABLE_END, new_body=table
    )
    _write_text(DATASETS_INDEX, updated, dry_run=dry_run)


# -----------------------------
# DVC helpers (explicit)
# -----------------------------
def _dvc_add_components(dataset_dir: Path, component_names: Sequence[str], *, dry_run: bool) -> None:
    normalized = _normalize_component_names(component_names)

    def run_add(path: Path) -> int:
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

    for comp in normalized:
        comp_path = dataset_dir / comp
        dvc_file = dataset_dir / f"{comp}.dvc"
        if dvc_file.exists():
            print(f"[skip] {comp} already tracked ({dvc_file.name})")
            continue

        rc = run_add(comp_path)
        if rc != 0:
            raise SystemExit(rc)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Create/update dataset.yaml + README + datasets index (explicit components)."
    )
    p.add_argument("--name", required=True, help="Dataset folder name under data/ (e.g. dataset1)")
    p.add_argument("--tag", required=True, help="Dataset tag (e.g. domain/source label)")
    p.add_argument("--version", required=True, help="Dataset version (e.g. 0.1.0)")
    p.add_argument("--status", default="draft", choices=["draft", "active", "deprecated"])
    p.add_argument("--owner", default="")
    p.add_argument("--license", default="internal")
    p.add_argument("--description", default="")

    p.add_argument(
        "--components",
        nargs="+",
        default=None,
        help="Explicit dataset components (subfolders), e.g. --components raw target features",
    )
    p.add_argument(
        "--prune-components",
        action="store_true",
        help="If set, prune dataset.yaml components to exactly the explicit list passed via --components.",
    )

    p.add_argument("--dvc", action="store_true", help="Run `dvc add` for the explicit components only.")
    p.add_argument("--dry-run", action="store_true")

    args = p.parse_args()

    if args.dvc and not args.components:
        p.error("--dvc requires --components (explicit list), e.g. --components raw target")

    dataset_dir = DATA_DIR / args.name
    dataset_dir.mkdir(parents=True, exist_ok=True)

    today = dt.date.today().isoformat()

    # 1) Load existing YAML, merge required fields
    yaml_path = _dataset_yaml_path(dataset_dir)
    meta = _load_dataset_yaml(yaml_path)

    meta.setdefault("created", today)
    meta["updated"] = today

    meta["name"] = args.name
    meta["tag"] = args.tag
    meta["version"] = args.version
    meta["status"] = args.status
    meta["owner"] = args.owner or meta.get("owner", "")
    meta["license"] = args.license or meta.get("license", "internal")

    if args.description:
        meta["description"] = args.description
    else:
        meta.setdefault("description", "")

    meta.setdefault("lineage", {"sources": [], "transforms": []})
    meta.setdefault("splits", {})
    meta.setdefault("notes", [])

    # 2) Components: explicit only
    if args.components:
        _ensure_explicit_component_entries(
            meta,
            dataset_dir,
            args.components,
            prune_to_explicit=bool(args.prune_components),
        )
    else:
        # No auto-discovery. Keep whatever YAML already has (or empty).
        meta.setdefault("components", {})

    _save_dataset_yaml(yaml_path, meta, dry_run=args.dry_run)
    print(f"Updated {yaml_path.relative_to(REPO_ROOT)}")

    # 3) README from YAML
    readme_path = dataset_dir / "README.md"
    existing_readme = _read_text(readme_path)
    new_readme = _make_readme_from_yaml(meta, dataset_dir, existing_readme)
    _write_text(readme_path, new_readme, dry_run=args.dry_run)
    print(f"Updated {readme_path.relative_to(REPO_ROOT)}")

    # 4) datasets.md rebuild from all dataset.yaml
    all_meta: List[Dict[str, Any]] = []
    for y in _find_all_dataset_yamls():
        m = _load_dataset_yaml(y)
        if m.get("name"):
            all_meta.append(m)

    if not any(m.get("name") == args.name for m in all_meta):
        all_meta.append(meta)

    _update_datasets_md(all_meta, dry_run=args.dry_run)
    print(f"Updated {DATASETS_INDEX.relative_to(REPO_ROOT)}")

    # 5) DVC add: explicit components only
    if args.dvc:
        _dvc_add_components(dataset_dir, args.components or [], dry_run=args.dry_run)

    # 6) Next steps (Windows-friendly: cmd.exe doesn't expand ** globs)
    print("\nNext:")
    add_parts = [
        str(yaml_path.relative_to(REPO_ROOT)),
        str(readme_path.relative_to(REPO_ROOT)),
        str(DATASETS_INDEX.relative_to(REPO_ROOT)),
    ]
    print("  git add " + " ".join(add_parts))
    if args.dvc:
        print("  git add *.dvc")
        print(f"  git add {dataset_dir.relative_to(REPO_ROOT)}/.gitignore")
    print(f'  git commit -m "Add/update dataset {args.name}"')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
