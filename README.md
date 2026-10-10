# cuttle.fish

Private fish with your existing history. Search, recall, and autosuggestions
work normally. New commands stay in memory until exit and never merge back.

Requires **fish 4.0+**, a Unix terminal, `/bin/sh`, and `/bin/cat`.
Tested on macOS with **fish 4.5.0** and **tmux 3.6a**.

Try from this checkout:

```fish
source functions/cuttle.fish
cuttle
```

Or install (adjust the path for a custom fish config directory):

```fish
mkdir -p ~/.config/fish/functions
cp functions/cuttle.fish ~/.config/fish/functions/cuttle.fish
```

Run `cuttle` in fish or a tmux pane. The prompt replaces the username in leading
`user@host` with **🥷**, keeping the host; otherwise it prefixes **🥷**.
`exit` or Ctrl-D restores the parent shell.

- History is a fixed snapshot, including in-memory entries; no live syncing,
  temporary history files, or archives. The parent's `cuttle` entry is expected.
- Normal config, directory, and exported environment carry over; local variables,
  runtime-defined functions, and jobs do not.
- **Keep `fish_history` empty in the child.** Setting a namespace can enable disk
  history; startup config that sets one is rejected.
- Privacy covers fish history only, not files, application histories, scrollback,
  or recording plugins.

Tests (Python 3; isolated fixtures, real PTYs, optional tmux):

```sh
python3 tests/test_cuttle.py
```
