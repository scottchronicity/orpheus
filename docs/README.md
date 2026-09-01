# Orpheus documentation

This folder is the source of the Orpheus documentation site. The same files are
readable three ways: as plain Markdown at the command line, browsed here on
GitHub, and as the built site. Start at [`index.md`](index.md), which routes you
by what you came to do.

## Start where you are

| If you want to… | Start here |
| --- | --- |
| Decide whether this is the right tool | [How Orpheus compares](comparison.md) |
| Use the dashboard | [User Guide](user-guide/index.md) |
| Install it yourself | [Installation](INSTALLATION.md) · [with an AI assistant](llm-assisted-install.md) |
| Set it up on your platform | [macOS](MACOS_QUICKSTART.md) · [Linux](LINUX_QUICKSTART.md) · [Jetson](JETSON_QUICKSTART.md) · [Windows](WINDOWS_QUICKSTART.md) |
| Run it safely | [Security](security.md) · [Operator's Manual](operator-manual/index.md) |
| Understand the data | [Data models](Orpheus_Standard_Data_Models.md) · [Event schemas](schemas/README.md) |
| Change how it works | [Architecture](ARCHITECTURE.md) · [Contributing](https://github.com/scottchronicity/orpheus/blob/main/CONTRIBUTING.md) · [Decision records](adr/) |
| Write documentation | [Voice and audience](contributing/voice-and-audience.md) |
| Work on responding agents or vision | ["I want to work on responding and vision"](index.md) |

[What's new](whats-new.md) covers this release in plain language.

## How this folder is organized

- `operator-manual/`, `INSTALLATION.md`, the quickstarts, `runbooks/` — installing,
  configuring, deploying, and keeping it running.
- `user-guide/`, `ORPHEUS_UI.md` — using the dashboard.
- `ARCHITECTURE.md`, `adr/`, `designs/`, `schemas/` — how it works and why.
- `contributing/`, `agent-instructions/`, `TESTING.md` — changing Orpheus. Written
  for humans and coding agents alike; there is one documentation tree, not a
  separate one for machines.
- `copilot-workspace-instructions/` — file-pattern instructions GitHub Copilot loads
  automatically. Tool configuration rather than documentation, so it is not part of
  the site.
- `assets/`, `stylesheets/` — images and styling for the built site.

## Adding a page

Put it where its reader will look for it, add it to the `nav:` in
[`mkdocs.yml`](https://github.com/scottchronicity/orpheus/blob/main/mkdocs.yml), and read
[Voice and audience](contributing/voice-and-audience.md) first. Preview locally with
`make docs-serve` while you write; `make docs-build` is the strict build CI runs.

Before publishing, check it with `make docs-preview` instead. The published site
sits under a path prefix, and the dev server answers at the root — so link bases,
the search index and asset URLs behave differently there than they will in
production. `docs-preview` builds the real site and serves it at the real prefix,
which is the only local view that matches what a reader gets.

What the gates actually catch: `make docs-build` fails on a `nav:` entry pointing at a
page that does not exist, and `make guardrails` fails when a file under `designs/` or
`adr/` is missing from the nav. Nothing else is enforced — a page in another directory
left out of the nav builds fine (it is only reachable by URL), and in-page links are
not validated at all, because many of them deliberately point at source files outside
the site. Check your own links.
