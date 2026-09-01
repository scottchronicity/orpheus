# Installing with an AI assistant

You do not have to understand every step to run Orpheus. If you are comfortable
copying and pasting, an AI coding assistant (Claude Code, Cursor, Copilot, or a
chat assistant with terminal access) can do the install with you.

This page is written to be **handed to the assistant**. Copy the block below into it,
answer its questions, and use the troubleshooting table when something goes wrong.

## What you need first

- A Mac or a Linux machine with at least 8 GB of RAM that you can open a terminal on. A Raspberry Pi is not enough on its own — three models run at once; see [how Orpheus compares](comparison.md).
- A microphone. The built-in one is fine to start.
- About 10 GB of free disk: 1.5 GB of machine-learning models, the rest Python environments (PyTorch and ONNX are large).
- 30–60 minutes, most of it waiting for downloads.

## The prompt

```text
Help me install and run Orpheus, an open-source wildlife audio monitoring system,
on this machine. Work through it step by step and stop to show me the output if
anything looks wrong.

The repository is https://github.com/scottchronicity/orpheus and its own
documentation is the source of truth — read the quickstart for this operating
system in the docs/ directory before you start, and follow it rather than
improvising.

What I want at the end:
- Orpheus installed and running on this machine
- Its dashboard open in my browser
- Audio captured from my microphone, with detections appearing as sounds happen

Please:
1. Check the prerequisites for my platform and install anything missing, telling
   me what you are installing and why.
2. Clone the repository and fetch the machine-learning models (they are stored
   with Git LFS, so a plain clone is not enough).
3. Install the components using the repository's own make targets. Do not run
   pip or npm directly, and do not run the install as root.
4. Start the message broker first, then the rest of the stack.
5. Open the dashboard and confirm with me that it loads.
6. Make a test sound near the microphone and show me that a detection appeared.

If a step fails, show me the actual error before trying a fix, and prefer the
fix documented in the repository over a general-purpose one.
```

## When it goes wrong

These are the failures that actually happen. Hand the assistant the fix column.

| What you see | What it means | Fix |
|---|---|---|
| `could not find portaudio` or `No module named 'sounddevice'` | The audio library the capture agent needs is not installed system-wide. | Install it (`brew install portaudio libsndfile` on macOS, `apt install portaudio19-dev libsndfile1` on Debian/Ubuntu), then reinstall the components. |
| `❌ Python interpreter 'python3.9' not found.` | The wrong interpreter is being used. Orpheus pins an older Python because of the hardware it targets. | `uv python install 3.9.5`, then `export PYTHON_SYSTEM=$(uv python find 3.9.5)` and reinstall. |
| `FileNotFoundError: birdnet.onnx` or "models appear to be LFS pointers" | The model files downloaded as tiny placeholder stubs instead of real models. | `git lfs install && git lfs pull` in the repository, then start again. |
| `nats: no servers available for connection` or `Connection refused: 127.0.0.1:4222` | The message broker is not running. Everything talks through it. | Start it first, then the rest of the stack. On a development machine: `make dev-stack SVC=backplane`. |
| The dashboard address does not load | Something else is using the port, or the backend did not start. | Check the service log for the UI backend. On a development machine the frontend picks the next free port if its default is taken — the actual address is printed in its log. |
| No detections, but everything is running | Usually microphone permissions, or the microphone is not the default input. | On macOS, allow terminal access to the microphone in System Settings → Privacy & Security. Check the capture agent's log: it prints which input device it opened. |
| `Cannot update time stamp of directory ... egg-info` | A previous install was run with `sudo` and left root-owned files. | Remove the offending `*.egg-info` directories and reinstall without `sudo`. |

## After it is running

- [Take the dashboard tour](user-guide/index.md) — what each page shows.
- [Tune it](operator-manual/index.md#2-configuration) — detection sensitivity,
  retention, optional features.
- Make a sound the system should catch and watch it arrive. That is the test that
  matters.

**Keep the assistant honest.** If it starts inventing commands, point it back at the
repository's quickstart for your platform. Everything it needs is documented there,
and the make targets are the supported path — a hand-rolled `pip install` will work
until it silently does not.
