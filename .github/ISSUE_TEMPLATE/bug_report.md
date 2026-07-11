---
name: Bug report
about: darnlink did something wrong (broke a link, wrong repair, crash…)
title: ''
labels: bug
---

**What happened**
A clear description of the bug.

**Minimal reproduction**
The smallest tree + command that shows it. For example:

```
docs/a.md:  See [x](b.md) <!-- uuid: … -->
$ darnlink . --write
```

**Expected vs actual**
What you expected darnlink to do, and what it did instead.

**Environment**
- darnlink version / commit (or `uvx --from git+…@vX.Y.Z`):
- OS (Linux/macOS/Windows) and line endings (LF/CRLF):
- Python version:
