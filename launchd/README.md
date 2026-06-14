# pilezero launchd LaunchAgent

This directory contains a macOS LaunchAgent plist that triggers the pilezero
pipeline whenever new files appear in the incoming scan folder, plus a 30-minute
periodic backstop.

## Prerequisites

- `uv` installed and accessible (`which uv` to find its path).
- Homebrew installed (`brew --prefix` must succeed).
- `~/.pilezero/` populated with `config.toml`, `senders.toml`, and
  `routing.toml` (copy from the repo and edit for your machine).

## Install

```bash
uv run python -m pilezero install-launchd
```

That's it. The command detects your `uv` path, Homebrew prefix, and
`incoming_dir` from `~/.pilezero/config.toml`, writes the plist to
`~/Library/LaunchAgents/`, and loads the agent via `launchctl`.

To preview what it would do without making changes:

```bash
uv run python -m pilezero install-launchd --dry-run
```

Re-run `install-launchd` any time you change the config or move the project.

## Checking status

```bash
launchctl list | grep pilezero
```

A PID in the second column means the job is currently running. Exit code 0 in
the third column means the last run succeeded.

For more detail:

```bash
launchctl print gui/$(id -u)/net.kenliu.pilezero
```

## Viewing logs

```bash
tail -f ~/.pilezero/launchd.out.log
tail -f ~/.pilezero/launchd.err.log
```

The pipeline also writes structured JSON logs to `~/.pilezero/log.jsonl`.

## Triggering a manual run

```bash
launchctl kickstart -k gui/$(id -u)/net.kenliu.pilezero
```

(`-k` kills any running instance first, then starts a fresh one.)

## Unloading the agent

```bash
launchctl unload -w ~/Library/LaunchAgents/net.kenliu.pilezero.plist
```

## Reference plist

`net.kenliu.pilezero.plist` in this directory is a reference template showing
the generated structure. It is not used directly by `install-launchd`.
