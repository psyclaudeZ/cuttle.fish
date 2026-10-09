# cuttle.fish

`cuttle` starts a private child fish with a fixed snapshot of your current shell's
visible command history. Inherited commands work with fish search, recall, and
autosuggestions. Commands entered in the child remain available there and
vanish when it exits; they are never merged back into the parent.

Requires fish **4.0+**, a Unix terminal, `/bin/sh`, and `/bin/cat`. Verified with
**fish 4.5.0** and **tmux 3.6a** on macOS; other versions/platforms are untested.

From this checkout, try it without installing:

```fish
source functions/cuttle.fish
cuttle
```

To install the autoloaded function yourself:

```fish
mkdir -p ~/.config/fish/functions
cp functions/cuttle.fish ~/.config/fish/functions/cuttle.fish
```

Use your custom fish config directory instead if applicable. For Fisher, this
repository uses its standard `functions/` layout.

Run `cuttle` from an interactive fish, including inside a tmux pane. Type `exit`
or press Ctrl-D to return to the original parent shell. Ctrl-C interrupts a
child command normally; it does not exit the child. The child exit status becomes
`cuttle`'s status. Nested `cuttle` sessions inherit their immediate parent's
history and discard their own additions on return. The launch command itself
may appear in the normal parent's history.

The child replaces the prompt's `user@host` segment with **🥷@dev**, leaving
the rest of the prompt intact. This works with fish's default prompt and themes
that use `prompt_login`; themes that build their own identity segment will need
to call that helper to show the marker. The parent's prompt returns on exit.
Nested sessions show the same identity once.

The snapshot includes the parent's available in-memory history. There is no
history merge, live synchronization, archive, or promotion. NUL-delimited entries
travel through a pipe into unexported child memory, never through a regular
temporary file, environment variable, or external program argument list. Fish's
`history append` imports entries as data, oldest first. Original timestamps and
path metadata are not transferred.

The child loads normal fish configuration and inherits the working directory
and exported environment, with `fish_history` cleared for private history.
Parent-local variables, runtime-defined functions, and jobs are not transferred.
Install/source `cuttle` in your config if you want it available for nested
invocation. Changes made by the child to its directory
or variables do not change the parent.

**History settings matter:** fish 4.5.0 allows setting a named `fish_history` to
re-enable persistence even after `--private`. `cuttle` refuses to import history
if startup configuration changes that variable to a nonempty name. Keep
`fish_history` empty throughout the child session; changing it can enable disk
history. Configuration that changes namespaces, clears history, disables
recording, or replaces fish's history behavior is incompatible. Arbitrary
configuration and plugins cannot be made safe by this function.

This isolates fish command history. It does not isolate filesystem changes,
application histories, terminal/tmux scrollback, or external history-recording
plugins. Normal config can still write its own settings/cache files.

Run the disposable tests with Python 3 and fish installed:

```sh
python3 tests/test_cuttle.py
```

The suite uses isolated HOME/XDG directories and real PTYs, plus a separate tmux
server when tmux is installed. It covers literal/multiline transport, snapshots
without merging, histories beyond `ARG_MAX`, search/recall/autosuggestions,
private command persistence, startup rejection, nesting, and terminal recovery.
It never installs into your fish config or reads or modifies your real history.
PTY/process-group operations must be allowed;
restricted sandboxes can make fish report an orphaned process and exit.
