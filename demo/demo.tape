# demo/demo.tape — VHS script for the README demo GIF.
# Render:  vhs demo/demo.tape        (needs: vhs + ttyd + ffmpeg)
# Shows a robust Markdown link surviving a file move: darnlink repairs the path by UUID.

Output demo.gif

Set Shell bash
Set FontSize 22
Set Width 1320
Set Height 640
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

# --- silent setup: clean prompt, temp dir, install darnlink, build the scenario ---
Hide
Type "export PS1='$ '" Enter
Type "clear" Enter
Type "rm -rf /tmp/darnlink-demo && mkdir -p /tmp/darnlink-demo && cd /tmp/darnlink-demo" Enter
Type "uv tool install git+https://github.com/txemi/darnlink >/dev/null 2>&1; export PATH=$HOME/.local/bin:$PATH" Enter
Sleep 12s
Type "mkdir docs architecture" Enter
Type "printf -- '---\nuuid: 7f3a1e2c-9b4d-4e6a-8c1f-2d3e4a5b6c7d\n---\n# Design doc\n' > docs/design.md" Enter
Type "printf 'See the [design doc](docs/design.md) <!-- uuid: 7f3a1e2c-9b4d-4e6a-8c1f-2d3e4a5b6c7d -->\n' > guide.md" Enter
Type "clear" Enter
Show

# --- the story ---
Type "# A robust link carries the target's uuid inline:" Enter
Sleep 800ms
Type "cat guide.md" Enter
Sleep 2s

Type "# Reorganise — move the target to another folder:" Enter
Sleep 700ms
Type "mv docs/design.md architecture/design.md" Enter
Sleep 1500ms

Type "# The path is now stale. Heal it:" Enter
Sleep 700ms
Type "darnlink . --write" Enter
Sleep 2500ms

Type "# The link was repaired automatically — new path, same uuid:" Enter
Sleep 700ms
Type "cat guide.md" Enter
Sleep 3s
