# Voice and audience

Read this before writing documentation. It applies to humans and to coding agents,
and it exists so that pages written years apart by different authors still read like
one project talking.

## Who reads this

Five profiles cover almost everyone who arrives. They are a **writer's tool** — you
use them to decide what a page assumes and how much it explains.

| Profile | Arrives wanting | Assumes |
|---|---|---|
| **Curious observer** | To know what is around their home. May never open a terminal. | Nothing technical. Explain in ordinary language or link to someone who will do it for them. |
| **Assisted installer** | To hand the work to an AI assistant and supervise it. | Can copy, paste, and read an error. Needs exact commands and named failure modes, not prose about concepts. |
| **Hobbyist operator** | To run it on their own hardware. | Comfortable with SSH, a terminal, editing YAML. Not necessarily with Python packaging or systemd internals. |
| **Data-minded user** | Trustworthy observations — provenance, accuracy, export, sharing. | Domain literacy, not necessarily software literacy. Be precise about what the data is and is not. |
| **Contributor** | To change or extend Orpheus. | Reads code. Wants the seams, the constraints, and the gates — not a tutorial. |

Two more appear occasionally: someone running Orpheus across several machines, and
someone deciding whether to use it at all. The [comparison page](../comparison.md)
is written for the latter.

## The rules

**Never use the profile labels in reader-facing prose.** No page says "this section
is for the hobbyist operator". Readers do not think of themselves in our categories,
and being sorted into one is alienating. Phrase choices as the reader's own goal
instead — *"I'm setting this up on my own hardware"* — and let them self-select.

**Pick one reader per page and hold it.** The most common failure is a page that
opens for a beginner and ends in implementation detail. If a page must serve two
audiences, split it, or put the second audience behind a clearly-labelled link at the
bottom.

**Write like a person, to a person.** Second person, active voice, ordinary words.
"Turn this on when your dashboard is slow" beats "this feature may be enabled in
scenarios exhibiting suboptimal query performance."

**Accuracy over volume.** Verify a claim against the code or config before writing
it. A short page that is true is worth more than a thorough one that is half stale.
Never document intent as though it shipped.

**Say what it costs.** Every feature has a downside, every alternative has a case.
Pages that only sell are not trusted, and readers find out anyway.

**No change narratives.** Documentation describes what is true now, not how it got
that way. "Previously X, now Y" belongs in a decision record or the release notes,
not in a reference page. The exception is an upgrade path, where the change *is* the
subject.

## The funnel: how someone reaches an answer

Nobody reads this site front to back — neither a person nor an agent with a limited
context window. Design for **arrive → orient → jump**:

- **Every hub page opens with what is under it**, one line per child. A section index
  that just lists filenames makes the reader open all of them.
- **Every page says where it sits** in a sentence or two: what this covers, and what
  the neighboring thing covers instead. Someone who landed from a search should be
  able to tell within seconds whether they are in the right place.
- **Link prerequisites explicitly.** If a page assumes the broker is installed, link
  the page that installs it rather than assuming a reading order.
- **Keep headings stable.** They are anchor targets for deep links from other pages,
  from issues, and from agent instructions. Renaming one silently breaks them.
- **Point, do not restate.** If another page already explains something, link it. Two
  copies of an explanation become two different explanations.

## Write vanilla Markdown

The same files are read three ways: as plain text at a command line (by people and
by coding agents), rendered by github.com when someone browses the `docs/` folder,
and built into the documentation site. Headings, lists, tables, fenced code, and
relative links behave identically in all three. Material's own syntax — admonition
blocks, content tabs, attribute lists — renders as literal junk in the first two,
so a page that leans on it is readable in only one of the three places.

- **Do** write in the common subset, and let `docs/stylesheets/extra.css` handle
  presentation so the source stays clean.
- **Don't** reach for site-only syntax unless the page is explicitly site-only, and
  say so at the top of it when you do.

## Where a new page goes

| It explains… | It belongs in |
|---|---|
| Installing, configuring, deploying, running, fixing | Operator's Manual |
| What a user sees or does in the dashboard | User Guide |
| How something works, or why it was built that way | Architecture & Design (a decision record if it is a decision) |
| How to change Orpheus safely | Coding & Contributing |
| A procedure performed against a live system | Runbooks |

Every new page must be added to the site navigation in `mkdocs.yml` — a repository
guardrail fails the build otherwise. Prefer
extending an existing page over adding one; add a page when a topic genuinely stands
on its own.

Before a public release, the same reader profiles are turned adversarial in
[Pre-release Review Lenses](release-review.md) — reviewers adopt one hostile
role each and report what they find.
