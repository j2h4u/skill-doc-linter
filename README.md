# skill-doc-linter

**A small agent skill for finding disconnected Markdown documentation.**

AI-generated and agent-maintained documentation tends to grow sideways: new notes, runbooks, and skill references appear, but they are not always linked from `AGENTS.md`, `README.md`, `SKILL.md`, or `CLAUDE.md`. Those orphan files become invisible to future agents even when the information is still useful.

This skill packages a deterministic graph check for that problem. It scans local Markdown references, Claude-style `@path` references, and selected skill frontmatter links, then reports the smallest disconnected problem graph as actionable terminal trees.

## Usage

```bash
python3 scripts/lint_doc_graph.py --scan-root .
```

Strict single-entrypoint mode:

```bash
python3 scripts/lint_doc_graph.py AGENTS.md --scan-root .
```

## Skill

Agents should read [SKILL.md](SKILL.md) for the workflow and use [scripts/lint_doc_graph.py](scripts/lint_doc_graph.py) for the actual check.

## License

No license has been selected yet.
