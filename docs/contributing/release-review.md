# Pre-release review lenses

Before a release that strangers will see, Orpheus gets reviewed through a set of
hostile lenses. Each lens is a role: a reviewer — a person or an agent — adopts
one, reads the change with that role's priorities, and reports what they find.
The lenses are deliberately adversarial. The goal is to meet the objections
before the public does.

This is the reviewing counterpart to [Voice & Audience](voice-and-audience.md),
which describes who we *write* for. Several lenses below are those same readers,
in a bad mood.

## How to run a pass

1. Pick the lenses that fit the release. A documentation-heavy release wants the
   docs and install lenses; a transport change wants correctness and operations.
2. Give each reviewer **one** lens. Reviewers work independently and must not
   see each other's findings — shared context breeds agreement, and agreement is
   not the product.
3. Reviewers **report; they do not fix.** Findings land as a list; the fixes are
   chosen and batched afterwards. A reviewer who fixes as they go stops
   reviewing.
4. Every finding carries evidence: a file and line, or a command and its output,
   or a quoted doc sentence. "Feels unpolished" is not a finding; "the install
   page tells you to run a target that no longer exists" is.
5. Where a false positive is expensive — security claims, "this is already
   done" claims — have a second reviewer try to *refute* each finding before it
   reaches the list. Anything that cannot be demonstrated in the code is dropped.
6. Order matters when one lens feeds another: audit what is claimed done before
   critiquing what remains.

## The lenses

### Claims auditor

Reads every "done" claim — release notes, the issue ledger, closed issues,
README boasts — and checks it against the code. Produces: claims that are false,
partial, or unverifiable. Run it first; its output corrects the material every
other lens reads.

### Roadmap critic

Reads what remains — the open ledger — as a stranger deciding whether to invest
attention. Is it coherent, honest, and appealing? Does it read like a project
going somewhere, or a junk drawer? Are the "good first issue" items genuinely
approachable by someone who has never seen the codebase? Produces: items that
are stale, vague, duplicated, or intimidating for the wrong reasons.

### Skeptical evaluator

Arrives from a link, gives the project five minutes, and looks for reasons to
leave. Compares it to the obvious alternatives and asks why anyone would run
this instead. Produces: unanswered objections, missing comparisons, claims that
sound like marketing, and anything in the first screen that reads as hobbyist
where it should read as careful.

### Security prodder

Asks how hard this is to abuse, assuming an attacker on the same network and a
curious stranger on the internet. Looks at what listens, what authenticates,
what ships with defaults, what lands in configs and logs, and what the platform
constraints cost. Produces: exposures ranked by what an attacker actually gains.
Honesty is the deliverable — a documented weakness beats a silent one, and
security theatre is itself a finding.

### Install-from-zero

Follows the installation documentation literally, on a clean machine, with no
prior knowledge and no willingness to guess. Every stumble is a finding: a
missing prerequisite, a command that assumes a directory, an error with no
recovery path, a step that silently requires hardware. Produces: the ordered
list of places a first-time user gives up.

### Documentation editor

Checks that each reader has a path from arrival to success, that pages say where
they sit and what comes next, and that nothing points at a file that moved.
Produces: dead ends, orphaned pages, stale commands, tone that drifts from the
house voice, and places where the reader must already know the answer to find
the answer.

### Contributor onboarding

Tries to land a first contribution: clone, build, test, find something to work
on, understand the review bar. Produces: everything between "I would like to
help" and "my change is merged" that is undocumented, broken, or discouraging.

## Reporting

One list per lens: severity, evidence, and the smallest fix that resolves it.
Group by lens so a reader can see which perspective raised what — a finding that
only the security lens cares about is a different decision from one that three
lenses hit independently. Record what was fixed and what was consciously
accepted; an accepted weakness with a reason is a legitimate outcome, a
forgotten one is not.
