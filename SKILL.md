---
name: doc-linter
description: Check AI-facing technical documentation for disconnected Markdown graph nodes. Use when maintaining AGENTS.md, CLAUDE.md, SKILL.md, README.md, generated docs, runbooks, or skill references, and you need to verify that local Markdown files are reachable from known entrypoints instead of becoming orphaned context.
---

# Documentation Graph Linting

Use this skill to keep AI-maintained documentation discoverable. The bundled script checks local Markdown links, Claude-style `@path` references, and selected skill frontmatter references, then reports only the disconnected problem graph.

## Run

From the repository or documentation root:

```bash
python3 /path/to/skill-doc-linter/scripts/lint_doc_graph.py --scan-root .
```

For strict single-entrypoint checks:

```bash
python3 /path/to/skill-doc-linter/scripts/lint_doc_graph.py AGENTS.md --scan-root .
python3 /path/to/skill-doc-linter/scripts/lint_doc_graph.py SKILL.md --scan-root .
```

If no entrypoint is passed, the script starts from known entrypoints found in the scan root:

- `AGENTS.md`
- `README.md`
- `SKILL.md`
- `CLAUDE.md`

## Interpret output

- `? ── file.md` means the file has no incoming link from the reachable documentation graph.
- `Link these orphan tree roots...` is usually the cheapest fix: link the shown root from an entrypoint; its children become reachable too.
- `Decide where these standalone orphan pages belong...` means the file has no local Markdown parent; choose the right taxonomy location before linking it.
- `Fix broken local references...` means an existing local link points to a missing file/path.

Do not blindly link every orphan from the nearest entrypoint. Prefer a small taxonomy-preserving fix: connect the right parent/index page, archive obsolete generated notes, and keep top-level agent files short.
