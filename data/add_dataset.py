from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

import yaml
from jinja2 import Environment, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
DATA_INDEX_MD = DATA_DIR / "README.md"

# data/<dataset>/dvc/<component>/...
DVC_SUBDIR_NAME = "dvc"
GIT_REMOTE_NAME = "origin"
DATASET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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
| `{{ c.path }}` | {{ c.description or "_…_" }} | {{ ("`" ~ c.schema ~ "`") if c.schema else "_…_" }} | {{ ("`" ~ c.produced_by ~ "`") if c.produced_by else "_…_" }} | _No versions yet — run the script after adding data._ |
{% endif %}

{%- endfor %}

{%- else %}

_No components discovered yet. Add folders under `data/{{ name }}/{{ dvc_subdir }}/` and rerun._

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


class AddDatasetError(RuntimeError):
    """Raised when add_dataset operations fail."""


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


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


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


def _dataset_tag(dataset_name: str, tag_version: int) -> str:
    return f"{dataset_name}-v{tag_version}"


def _discover_components(dataset_dir: Path) -> List[str]:
    dvc_root = dataset_dir / DVC_SUBDIR_NAME
    if not dvc_root.is_dir():
        return []
    comps: List[str] = []
    for p in sorted(dvc_root.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            comps.append(p.name)
    return comps


def _all_components(meta: Dict[str, Any], discovered: List[str]) -> List[str]:
    meta_components = _as_dict(meta.get("components"))
    meta_names = [k for k in meta_components.keys() if isinstance(k, str) and k]
    return sorted(set(discovered) | set(meta_names))


def _normalize_tags(entry: Dict[str, Any]) -> List[str]:
    """
    Accept legacy shapes:
      - list[str]
      - single string
      - None / missing
    Always returns list[str].
    """
    raw = entry.get("tags")
    if isinstance(raw, list):
        return [str(t) for t in raw if str(t)]
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    return []


def _ensure_component_entries(meta: Dict[str, Any], components: List[str]) -> None:
    # IMPORTANT: assign back so we don't mutate a detached copy
    meta_components = _as_dict(meta.get("components"))
    meta["components"] = meta_components

    for cname in components:
        entry = _as_dict(meta_components.get(cname))
        meta_components[cname] = entry

        entry.setdefault("path", cname)
        entry.setdefault("description", "")
        entry.setdefault("schema", None)
        entry.setdefault("produced_by", None)

        entry["tags"] = _normalize_tags(entry)


def _append_tag_for_all_components(meta: Dict[str, Any], components: List[str], tag: str) -> None:
    # IMPORTANT: assign back so we don't mutate a detached copy
    meta_components = _as_dict(meta.get("components"))
    meta["components"] = meta_components

    for cname in components:
        entry = _as_dict(meta_components.get(cname))
        meta_components[cname] = entry

        tags = _normalize_tags(entry)
        if not tags or tags[-1] != tag:
            tags.append(tag)

        entry["tags"] = tags
        entry["tag"] = tags[-1]


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
        tags = _normalize_tags(raw)
        safe_components[cname] = {
            "path": str(raw.get("path", cname)),
            "description": str(raw.get("description", "")),
            "schema": raw.get("schema", None),
            "produced_by": raw.get("produced_by", None),
            "tags": tags,
        }

    return (
        tmpl.render(
            name=name,
            description=description,
            components=safe_components,
            components_order=components_order,
            dvc_subdir=DVC_SUBDIR_NAME,
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
        rows.append({"name": name, "status": str(m.get("status", "")), "n_components": len(comps), "rel_dir": rel_dir})

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


def _run(cmd: Iterable[str], *, cwd: Path) -> Tuple[int, str]:
    proc = subprocess.run(list(cmd), cwd=str(cwd), capture_output=True, text=True)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, out.strip()


def _run_checked(cmd: Iterable[str], *, error_context: str) -> str:
    command = list(cmd)
    rc, out = _run(command, cwd=REPO_ROOT)
    if rc != 0:
        detail = f": {out}" if out else ""
        raise AddDatasetError(f"{error_context}{detail}")
    return out


def _run_dvc_add(path: Path) -> None:
    _run_checked(["dvc", "add", str(path)], error_context=f"dvc add failed for {path}")


def _dvc_file_for_output_dir(output_dir: Path) -> Path:
    # data/<dataset>/dvc  ->  data/<dataset>/dvc.dvc
    return output_dir.with_suffix(".dvc")


def _repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _path_differs_from_head(path: Path) -> bool:
    relative_path = _repo_relative(path)
    rc, out = _run(["git", "diff", "--quiet", "HEAD", "--", relative_path], cwd=REPO_ROOT)
    if rc == 1:
        return True
    if rc != 0:
        raise AddDatasetError(f"Unable to compare {relative_path} with HEAD: {out}")

    rc, out = _run(["git", "ls-files", "--error-unmatch", "--", relative_path], cwd=REPO_ROOT)
    if rc == 0:
        return False
    if rc == 1:
        return path.exists()
    raise AddDatasetError(f"Unable to inspect {relative_path}: {out}")


def _dvc_add_dataset(dataset_dir: Path) -> Tuple[bool, Path]:
    dvc_output_dir = dataset_dir / DVC_SUBDIR_NAME
    dvc_output_dir.mkdir(parents=True, exist_ok=True)

    dvc_file = _dvc_file_for_output_dir(dvc_output_dir)
    _run_dvc_add(dvc_output_dir)

    return _path_differs_from_head(dvc_file), dvc_file


def _dataset_dir(dataset_name: str) -> Path:
    if not DATASET_NAME_PATTERN.fullmatch(dataset_name):
        raise AddDatasetError(
            "Dataset name must start with a letter or number and contain only letters, numbers, '.', '_', or '-'."
        )
    return DATA_DIR / dataset_name


def _require_clean_index() -> None:
    rc, out = _run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    if rc == 0:
        return
    if rc == 1:
        raise AddDatasetError("Git index contains staged changes. Commit or unstage them before publishing a dataset.")
    raise AddDatasetError(f"Unable to inspect the Git index: {out}")


def _prepare_publication() -> str:
    branch = _run_checked(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        error_context="Dataset publishing requires a checked-out Git branch",
    )
    _require_clean_index()
    _run_checked(
        ["git", "remote", "get-url", GIT_REMOTE_NAME],
        error_context=f"Git remote '{GIT_REMOTE_NAME}' is not configured",
    )
    _run_checked(
        ["git", "fetch", GIT_REMOTE_NAME, branch, "--tags"],
        error_context=f"Unable to fetch {GIT_REMOTE_NAME}/{branch}",
    )
    counts = _run_checked(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{GIT_REMOTE_NAME}/{branch}"],
        error_context=f"Unable to compare HEAD with {GIT_REMOTE_NAME}/{branch}",
    ).split()
    if counts != ["0", "0"]:
        ahead, behind = counts if len(counts) == 2 else ("?", "?")
        raise AddDatasetError(
            f"Current branch must match {GIT_REMOTE_NAME}/{branch} before publishing (ahead {ahead}, behind {behind})."
        )
    return branch


def _next_tag_version(dataset_name: str) -> int:
    prefix = f"{dataset_name}-v"
    output = _run_checked(
        ["git", "tag", "--list", f"{prefix}*"],
        error_context=f"Unable to inspect tags for {dataset_name}",
    )
    versions: List[int] = []
    for tag in output.splitlines():
        suffix = tag.removeprefix(prefix)
        if suffix.isdigit() and tag == f"{prefix}{suffix}":
            versions.append(int(suffix))
    return max(versions, default=0) + 1


def _unstage(paths: Iterable[Path]) -> None:
    relative_paths = [_repo_relative(path) for path in paths]
    _run(["git", "reset", "--", *relative_paths], cwd=REPO_ROOT)


def _push_dvc_data(dvc_file: Path, gitignore_path: Path) -> None:
    dvc_relative = _repo_relative(dvc_file)
    try:
        _run_checked(["dvc", "push", dvc_relative], error_context=f"dvc push failed for {dvc_relative}")
    except AddDatasetError:
        _unstage([dvc_file, gitignore_path])
        raise


def _publish_git(
    *,
    dataset_name: str,
    branch: str,
    paths: Iterable[Path],
    tag: str | None,
) -> None:
    publication_paths = list(paths)
    relative_paths = [_repo_relative(path) for path in publication_paths]
    _run_checked(
        ["git", "add", "--", *relative_paths],
        error_context="Unable to stage generated dataset files",
    )

    rc, out = _run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    if rc == 0:
        print("[publish] no Git changes to commit")
        return
    if rc != 1:
        raise AddDatasetError(f"Unable to inspect staged dataset files: {out}")

    try:
        _run_checked(
            ["git", "commit", "-m", f"Add/update dataset {dataset_name}"],
            error_context="Unable to commit dataset changes",
        )
    except AddDatasetError:
        _unstage(publication_paths)
        raise

    push_command = ["git", "push", "--atomic", GIT_REMOTE_NAME, f"HEAD:refs/heads/{branch}"]
    if tag is not None:
        _run_checked(["git", "tag", tag], error_context=f"Unable to create tag {tag}")
        push_command.append(f"refs/tags/{tag}:refs/tags/{tag}")

    _run_checked(
        push_command,
        error_context=(
            "Git push failed; the commit and any dataset tag remain local. "
            "Resolve the remote issue and push them manually"
        ),
    )
    print(f"[publish] pushed commit{' and ' + tag if tag else ''} to {GIT_REMOTE_NAME}/{branch}")


def main() -> int:
    p = argparse.ArgumentParser(description="Create or update a dataset, version it, and publish it to DVC and Git.")
    p.add_argument("name", help="Dataset folder name under data/ (e.g. dataset1)")
    p.add_argument("--status", choices=["draft", "active", "deprecated"])
    p.add_argument("--description", default="", help="Dataset description shown in README (optional).")
    args = p.parse_args()

    dataset_dir = _dataset_dir(args.name)
    branch = _prepare_publication()
    dataset_dir.mkdir(parents=True, exist_ok=True)

    today = dt.date.today().isoformat()
    meta_path = dataset_dir / "dataset.yaml"

    meta = _read_yaml(meta_path)
    meta.setdefault("created", today)
    meta["updated"] = today
    meta["name"] = args.name
    if args.status:
        meta["status"] = args.status
    else:
        meta.setdefault("status", "draft")

    if args.description:
        meta["description"] = args.description
    else:
        meta.setdefault("description", "")

    raw_tag_version = meta.get("tag_version", 0)
    tag_version = int(raw_tag_version) if isinstance(raw_tag_version, int) else 0

    discovered = _discover_components(dataset_dir)
    components = _all_components(meta, discovered)

    _ensure_component_entries(meta, components)

    changed_any, dvc_file = _dvc_add_dataset(dataset_dir)
    dvc_rel = dvc_file.relative_to(REPO_ROOT)
    gitignore_path = dataset_dir / ".gitignore"

    if changed_any:
        print(f"[updated] {dvc_rel} changed")
        tag_version = _next_tag_version(args.name)
        current_tag = _dataset_tag(args.name, tag_version)
        _push_dvc_data(dvc_file, gitignore_path)
        print(f"[dvc] pushed data for {args.name}")
        meta["tag_version"] = tag_version
        print(f"[tag] data changed -> bump tag_version to v{tag_version}")
    else:
        meta["tag_version"] = tag_version
        print(f"[tag] no data change -> keep tag_version at v{tag_version}")

    current_tag = _dataset_tag(args.name, tag_version)

    _append_tag_for_all_components(meta, components, current_tag)

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

    _publish_git(
        dataset_name=args.name,
        branch=branch,
        paths=[meta_path, readme_path, DATA_INDEX_MD, dvc_file, gitignore_path],
        tag=current_tag if changed_any else None,
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AddDatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
