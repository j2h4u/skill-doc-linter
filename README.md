# Documentation Graph Linter

A small agent skill and deterministic command-line check for finding disconnected
Markdown documentation. It helps keep agent-maintained notes, runbooks, and
skill references discoverable from documentation entrypoints.

## What it does

The bundled [script](scripts/lint_doc_graph.py) scans local Markdown links,
Claude-style `@path` references, and selected skill frontmatter links. It
reports disconnected documentation as actionable terminal trees. The
[skill workflow](SKILL.md) explains how to choose entrypoints and interpret
results.

Run the script from the repository or documentation root:

```sh
python3 scripts/lint_doc_graph.py --scan-root .
```

To check reachability from one explicit entrypoint instead:

```sh
python3 scripts/lint_doc_graph.py AGENTS.md --scan-root .
```

The command checks documentation connections; review findings in context
before changing or deleting documents.

## Install

Clone the full repository into the agent skills directory:

```sh
mkdir -p ~/.agents/skills
git clone https://github.com/j2h4u/skill-doc-linter.git ~/.agents/skills/doc-linter
```

If the destination already exists, inspect it first; do not overwrite it. Reload
the skill according to your agent host's instructions. The script remains
available inside the clone for direct command-line use.

## Update

```sh
git -C ~/.agents/skills/doc-linter pull --ff-only
```

## Use

Ask your agent to check whether documentation is reachable, or invoke the
skill by name:

```text
$doc-linter Check the documentation graph for this repository.
```

For a direct check, use the script commands above from the checkout, adjusting
the entrypoint and scan root to the documentation being examined.

## License

[PolyForm Noncommercial 1.0.0](LICENSE.md) permits use under its stated terms.
For commercial use, request written permission from the copyright holder.
