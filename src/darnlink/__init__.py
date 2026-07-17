"""darnlink — auto-healing Markdown links.

Anchor Markdown links to a UUID so they survive file moves:
- repair: rewrite a robust link's path to wherever its UUID now lives.
- robustify: upgrade a plain link to a robust one.

Plain Markdown, no database, no editor lock-in. Dry-run by default.
See the project Constitution in .specify/memory/constitution.md.
"""

__version__ = "0.2.0"
