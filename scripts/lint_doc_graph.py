#!/usr/bin/env python3
"""Validate local Markdown documentation graph connectivity."""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urlparse

DEFAULT_SCAN_ROOT = Path.cwd()
DEFAULT_ENTRYPOINT_NAMES = ("AGENTS.md", "README.md", "SKILL.md", "CLAUDE.md")

INLINE_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REFERENCE_DEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
AT_REFERENCE_RE = re.compile(r"(?<![\w./-])@(?P<target>[A-Za-z0-9_./~+-]+(?:#[A-Za-z0-9_./-]+)?)")
IGNORED_SCHEMES = {"http", "https", "mailto"}
IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
FRONTMATTER_EDGE_FIELDS = {"license", "references", "subskills"}
FRONTMATTER_FILE_REF_FIELDS = {"hooks", *FRONTMATTER_EDGE_FIELDS}
FILE_LIKE_AT_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mdx",
    ".py",
    ".scss",
    ".sh",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
}


class Graph(NamedTuple):
    edges: dict[Path, set[Path]]
    incoming: dict[Path, set[Path]]
    broken: list[tuple[Path, str, str]]


class ProblemForest(NamedTuple):
    standalone_roots: list[Path]
    tree_roots: list[Path]
    unrooted_pages: list[Path]
    children_by_parent: dict[Path, list[Path]]


def markdown_files(scan_root: Path) -> set[Path]:
    files: set[Path] = set()
    for path in scan_root.rglob("*.md"):
        if path.is_file() and not any(part in IGNORED_DIRS for part in path.relative_to(scan_root).parts):
            files.add(path.resolve())
    return files


def iter_link_targets(text: str) -> list[str]:
    return [*INLINE_LINK_RE.findall(text), *REFERENCE_DEF_RE.findall(text)]


def strip_markdown_code(text: str) -> str:
    """Remove Markdown code blocks/spans before parsing Claude-style @ imports."""

    without_fences = re.sub(r"(?ms)^ {0,3}(```|~~~).*?^ {0,3}\\1\\s*$", "", text)
    return re.sub(r"`[^`\\n]*`", "", without_fences)


def iter_at_reference_targets(text: str) -> list[str]:
    """Return Claude Code style @path references outside Markdown code."""

    return [match.group("target") for match in AT_REFERENCE_RE.finditer(text)]


def should_validate_at_reference(target: str, resolved: Path) -> bool:
    """Keep likely Claude-style file refs; ignore decorators, aliases, packages, and routes."""

    without_fragment = strip_fragment(target)
    suffix = Path(without_fragment).suffix.lower()
    return resolved.exists() or without_fragment.endswith("/") or suffix in FILE_LIKE_AT_EXTENSIONS


def iter_frontmatter_targets(source: Path, text: str) -> list[str]:
    """Return recognized file references from simple YAML frontmatter fields."""

    frontmatter = frontmatter_block(text)
    if frontmatter is None:
        return []

    targets: list[str] = []
    current_field: str | None = None
    for raw_line in frontmatter.splitlines():
        current_field, line_targets = frontmatter_line_targets(source, raw_line, current_field)
        targets.extend(line_targets)

    return targets


def frontmatter_block(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None

    end = text.find("\n---", 4)
    if end == -1:
        return None
    return text[4:end]


def frontmatter_line_targets(
    source: Path,
    raw_line: str,
    current_field: str | None,
) -> tuple[str | None, list[str]]:
    stripped = raw_line.strip()
    if not stripped or raw_line.lstrip().startswith("#"):
        return current_field, []
    if raw_line.startswith((" ", "\t")):
        return current_field, indented_frontmatter_targets(source, stripped, current_field)
    return top_level_frontmatter_targets(source, raw_line)


def top_level_frontmatter_targets(source: Path, raw_line: str) -> tuple[str, list[str]]:
    key, _, remainder = raw_line.partition(":")
    field = key.strip()
    if field in FRONTMATTER_FILE_REF_FIELDS and remainder.strip():
        return field, frontmatter_value_targets(source, field, field, remainder.strip())
    return field, []


def indented_frontmatter_targets(source: Path, stripped: str, current_field: str | None) -> list[str]:
    if current_field not in FRONTMATTER_FILE_REF_FIELDS:
        return []

    key, separator, remainder = stripped.partition(":")
    if separator:
        return frontmatter_value_targets(source, current_field, key.strip(), remainder.strip())
    if stripped.startswith("- "):
        return frontmatter_value_targets(source, current_field, "", stripped[2:].strip())
    return []


def frontmatter_value_targets(source: Path, field: str, key: str, value: str) -> list[str]:
    cleaned = value.strip().strip("'\"")
    if field == "hooks" and key == "script" and is_path_like_frontmatter_value(cleaned):
        return [cleaned]

    if is_path_like_frontmatter_value(cleaned):
        return [frontmatter_target_for_field(field, cleaned)]

    if field == "references" and key:
        reference_file = source.parent / "references" / f"{key}.md"
        if reference_file.exists():
            return [f"references/{key}.md"]

    return []


def is_path_like_frontmatter_value(value: str) -> bool:
    if not value or any(char.isspace() for char in value):
        return False
    return value.startswith(("./", "../", "/")) or "/" in value or bool(Path(strip_fragment(value)).suffix)


def frontmatter_target_for_field(field: str, target: str) -> str:
    if field == "subskills" and not Path(strip_fragment(target)).suffix and not target.endswith("/"):
        return f"{target}/SKILL.md"
    return target


def strip_fragment(target: str) -> str:
    return target.split("#", 1)[0]


def is_ignored(target: str) -> bool:
    parsed = urlparse(target)
    if parsed.scheme in IGNORED_SCHEMES:
        return True
    return target.startswith("#") or not strip_fragment(target)


def resolve_local_target(source: Path, target: str, scan_root: Path) -> Path:
    without_fragment = unquote(strip_fragment(target))
    normalized = posixpath.normpath(without_fragment)
    if normalized.startswith("/"):
        return (scan_root / normalized.lstrip("/")).resolve()
    return (source.parent / normalized).resolve()


def display(path: Path, scan_root: Path) -> str:
    try:
        return str(path.relative_to(scan_root))
    except ValueError:
        return str(path)


def auto_entrypoints(scan_root: Path, files: set[Path]) -> list[Path]:
    roots = []
    for name in DEFAULT_ENTRYPOINT_NAMES:
        candidate = (scan_root / name).resolve()
        if candidate in files:
            roots.append(candidate)
    return roots


def lint(entrypoints: list[Path], scan_root: Path) -> int:
    scan_root = scan_root.resolve()
    entrypoints = [entrypoint.resolve() for entrypoint in entrypoints]
    files = markdown_files(scan_root)
    entrypoints = entrypoints or auto_entrypoints(scan_root, files)

    if not validate_entrypoints(entrypoints, files, scan_root):
        return 1

    graph = build_graph(files, scan_root)
    reachable = reachable_files(entrypoints, graph.edges)
    unreachable = sorted(files - reachable)
    entrypoints_text = entrypoint_label(entrypoints, scan_root)

    print_broken_references(graph.broken, scan_root)
    if unreachable:
        print_unreachable_suggestions(unreachable, graph.edges, graph.incoming, entrypoints_text, scan_root)

    if graph.broken or unreachable:
        return 1

    print(f"Documentation graph OK: {len(files)} markdown files reachable from {entrypoints_text}.")
    return 0


def validate_entrypoints(entrypoints: list[Path], files: set[Path], scan_root: Path) -> bool:
    if not entrypoints:
        print(f"no graph entrypoints found under scan root: {scan_root}", file=sys.stderr)
        return False

    missing_entrypoints = [entrypoint for entrypoint in entrypoints if entrypoint not in files]
    if not missing_entrypoints:
        return True

    print("graph entrypoints missing or outside scan root:", file=sys.stderr)
    for entrypoint in missing_entrypoints:
        print(f"  {entrypoint}", file=sys.stderr)
    return False


def build_graph(files: set[Path], scan_root: Path) -> Graph:
    edges: dict[Path, set[Path]] = defaultdict(set)
    incoming: dict[Path, set[Path]] = defaultdict(set)
    broken: list[tuple[Path, str, str]] = []

    for source in sorted(files):
        add_source_edges(source, files, scan_root, edges, incoming, broken)

    return Graph(edges, incoming, broken)


def add_source_edges(
    source: Path,
    files: set[Path],
    scan_root: Path,
    edges: dict[Path, set[Path]],
    incoming: dict[Path, set[Path]],
    broken: list[tuple[Path, str, str]],
) -> None:
    text = source.read_text(encoding="utf-8")
    link_text = strip_markdown_code(text)
    targets = [
        *[("markdown", target) for target in iter_link_targets(link_text)],
        *[("@", target) for target in iter_at_reference_targets(link_text)],
        *[("frontmatter", target) for target in iter_frontmatter_targets(source, text)],
    ]
    for kind, target in targets:
        add_target_edge(source, kind, target, files, scan_root, edges, incoming, broken)


def add_target_edge(
    source: Path,
    kind: str,
    target: str,
    files: set[Path],
    scan_root: Path,
    edges: dict[Path, set[Path]],
    incoming: dict[Path, set[Path]],
    broken: list[tuple[Path, str, str]],
) -> None:
    if is_ignored(target):
        return

    resolved = resolve_local_target(source, target, scan_root)
    if should_skip_target(kind, target, resolved):
        return
    if not resolved.exists():
        broken.append((source, kind, target))
        return
    if resolved.is_file() and resolved.suffix.lower() == ".md" and resolved in files:
        edges[source].add(resolved)
        incoming[resolved].add(source)


def should_skip_target(kind: str, target: str, resolved: Path) -> bool:
    if kind == "@" and not should_validate_at_reference(target, resolved):
        return True
    return kind == "markdown" and resolved.suffix.lower() != ".md"


def reachable_files(entrypoints: list[Path], edges: dict[Path, set[Path]]) -> set[Path]:
    reachable: set[Path] = set()
    queue: deque[Path] = deque(entrypoints)
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        queue.extend(sorted(edges[current] - reachable))
    return reachable


def print_broken_references(broken: list[tuple[Path, str, str]], scan_root: Path) -> None:
    if not broken:
        return

    print("Fix broken local references:")
    for source, kind, target in broken:
        print(f"  {display(source, scan_root)} -> {kind}:{target}")


def print_unreachable_suggestions(
    unreachable: list[Path],
    edges: dict[Path, set[Path]],
    incoming: dict[Path, set[Path]],
    entrypoints_text: str,
    scan_root: Path,
) -> None:
    forest = problem_forest(unreachable, edges, incoming)
    printed_in_trees: set[Path] = set()

    print("Suggested documentation fixes:")
    print_tree_root_suggestions(forest, entrypoints_text, scan_root, printed_in_trees)
    print_standalone_suggestions(forest, entrypoints_text, scan_root)
    print_unrooted_suggestions(forest, printed_in_trees, entrypoints_text, scan_root)


def problem_forest(
    unreachable: list[Path],
    edges: dict[Path, set[Path]],
    incoming: dict[Path, set[Path]],
) -> ProblemForest:
    unreachable_set = set(unreachable)
    children_by_parent = unreachable_children_by_parent(unreachable, edges, unreachable_set)
    incoming_from_unreachable = unreachable_incoming_by_page(unreachable, incoming, unreachable_set)
    roots = sorted(path for path in unreachable if not incoming_from_unreachable[path])
    standalone_roots = sorted(path for path in roots if not children_by_parent[path])
    tree_roots = sorted(path for path in roots if children_by_parent[path])
    unrooted_pages = sorted(unreachable_set - set(standalone_roots))
    return ProblemForest(standalone_roots, tree_roots, unrooted_pages, children_by_parent)


def unreachable_children_by_parent(
    unreachable: list[Path],
    edges: dict[Path, set[Path]],
    unreachable_set: set[Path],
) -> dict[Path, list[Path]]:
    return {
        path: sorted(child for child in edges[path] if child in unreachable_set)
        for path in unreachable
    }


def unreachable_incoming_by_page(
    unreachable: list[Path],
    incoming: dict[Path, set[Path]],
    unreachable_set: set[Path],
) -> dict[Path, set[Path]]:
    return {
        path: {parent for parent in incoming[path] if parent in unreachable_set}
        for path in unreachable
    }


def print_tree_root_suggestions(
    forest: ProblemForest,
    entrypoints_text: str,
    scan_root: Path,
    printed_in_trees: set[Path],
) -> None:
    if not forest.tree_roots:
        return

    print(
        f"  Link these orphan tree roots into an entrypoint ({entrypoints_text}); "
        "their child pages shown below will become reachable too:"
    )
    for root in forest.tree_roots:
        print_tree(root, forest.children_by_parent, scan_root, printed_in_trees)


def print_standalone_suggestions(
    forest: ProblemForest,
    entrypoints_text: str,
    scan_root: Path,
) -> None:
    if not forest.standalone_roots:
        return

    print(
        f"  Decide where these standalone orphan pages belong, then link them from "
        f"an entrypoint ({entrypoints_text}) or another reachable page; archive/remove them if obsolete:"
    )
    for path in forest.standalone_roots:
        print(f"    ? ── {display(path, scan_root)}")


def print_unrooted_suggestions(
    forest: ProblemForest,
    printed_in_trees: set[Path],
    entrypoints_text: str,
    scan_root: Path,
) -> None:
    unprinted = sorted(set(forest.unrooted_pages) - printed_in_trees)
    if not unprinted:
        return

    print(
        f"  Review these unreachable pages with no clear root; "
        f"link one page from each cluster into an entrypoint ({entrypoints_text}):"
    )
    for path in unprinted:
        print(f"    ? ── {display(path, scan_root)}")


def print_tree(
    root: Path,
    children_by_parent: dict[Path, list[Path]],
    scan_root: Path,
    printed: set[Path],
) -> None:
    print(f"    ? ── {display(root, scan_root)}")
    printed.add(root)
    print_tree_children(root, children_by_parent, scan_root, printed, "           ", {root})


def print_tree_children(
    parent: Path,
    children_by_parent: dict[Path, list[Path]],
    scan_root: Path,
    printed: set[Path],
    prefix: str,
    ancestors: set[Path],
) -> None:
    children = children_by_parent[parent]
    for index, child in enumerate(children):
        is_last = index == len(children) - 1
        branch = "└──" if is_last else "├──"
        cycle_suffix = " (cycle)" if child in ancestors else ""
        already_shown_suffix = " (also linked above)" if child in printed and child not in ancestors else ""
        print(f"{prefix}  {branch} {display(child, scan_root)}{cycle_suffix}{already_shown_suffix}")
        if child in ancestors or child in printed:
            continue
        printed.add(child)
        child_prefix = f"{prefix}      " if is_last else f"{prefix}  │   "
        print_tree_children(child, children_by_parent, scan_root, printed, child_prefix, {*ancestors, child})


def entrypoint_label(entrypoints: list[Path], scan_root: Path) -> str:
    if len(entrypoints) == 1:
        return display(entrypoints[0], scan_root)
    return ", ".join(display(entrypoint, scan_root) for entrypoint in entrypoints)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "entrypoint",
        nargs="?",
        type=Path,
        help="Optional Markdown file to start graph traversal from. If omitted, uses known entrypoints in scan root.",
    )
    parser.add_argument(
        "--scan-root",
        type=Path,
        default=None,
        help="Directory to scan recursively; defaults to the entrypoint's parent directory, or cwd when no entrypoint is provided.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    scan_root = args.scan_root or (args.entrypoint.parent if args.entrypoint else DEFAULT_SCAN_ROOT)
    entrypoints = [args.entrypoint] if args.entrypoint else []
    raise SystemExit(lint(entrypoints, scan_root))
