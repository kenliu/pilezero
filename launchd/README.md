# pilezero launchd LaunchAgent

This directory contains a macOS LaunchAgent plist that triggers the pilezero
pipeline whenever new files appear in the incoming scan folder, plus a 30-minute
periodic backstop.

## Prerequisites

- `uv` installed and accessible (run `which uv` to find its path).
- The pilezero project cloned at the path referenced in the plist.
- The log directory created: `mkdir -p ~/.pilezero`

## Setup steps

### 1. Edit the plist

Open `net.kenliu.pilezero.plist` and replace every occurrence of `USERNAME`
with your macOS short username (`whoami` prints it).

Also update the `uv` binary path in `ProgramArguments` if it differs from
`/opt/homebrew/bin/uv`. Common alternatives:

| Installation            | Path                              |
|-------------------------|-----------------------------------|
| Homebrew (Apple Silicon)| `/opt/homebrew/bin/uv`            |
| Homebrew (Intel)        | `/usr/local/bin/uv`               |
| pipx / standalone       | `/Users/USERNAME/.local/bin/uv`   |

Verify the incoming folder path in `WatchPaths` matches `incoming_dir` in
`config.toml` (default: `~/Dropbox/Scans/_Incoming`).

### 2. Create the log directory

```bash
mkdir -p ~/.pilezero
```

### 3. Install the plist

```bash
cp net.kenliu.pilezero.plist ~/Library/LaunchAgents/
```

### 4. Load the agent

```bash
launchctl load -w ~/Library/LaunchAgents/net.kenliu.pilezero.plist
```

The agent is now active. It will fire immediately (RunAtLoad), whenever the
incoming folder changes (WatchPaths), and every 30 minutes (StartInterval).

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

The pipeline also writes structured JSON logs to `~/.pilezero/log.jsonl`
(configured in `config.toml`).

## Triggering a manual run

```bash
launchctl kickstart -k gui/$(id -u)/net.kenliu.pilezero
```

(`-k` kills any running instance first, then starts a fresh one.)

## Unloading the agent

To stop and disable the agent:

```bash
launchctl unload -w ~/Library/LaunchAgents/net.kenliu.pilezero.plist
```

## After editing the plist

Unload, then reload:

```bash
launchctl unload ~/Library/LaunchAgents/net.kenliu.pilezero.plist
cp net.kenliu.pilezero.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/net.kenliu.pilezero.plist
```
