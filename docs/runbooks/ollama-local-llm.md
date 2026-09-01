# Running a local LLM alongside Orpheus

If you have a GPU workstation on the same network as your station, Ollama on it
is useful to Orpheus in several ways. Throughout this page, `LLMBOX` stands for
that machine — substitute your own hostname. (It is deliberately not
`OLLAMA_HOST`: that is a real Ollama variable with its own meaning, used once
below.)

## What it can and cannot do

A coding assistant's own reasoning runs on its vendor's models; you cannot point
one at Ollama as its brain. What the box gives you is a free, private,
always-on inference endpoint on your LAN (`http://LLMBOX:11434`,
OpenAI-compatible API) that you can build against and that Orpheus can use as a
component. Treat it as infrastructure, not as a replacement for the assistant.

## Uses, most valuable first

1. **A fully-local wildlife Q&A loop.** The read-only portal exists so an LLM
   can query Orpheus without reaching the private dashboard API. Point a local
   model at it — Ollama has MCP-capable clients, or write a thin script that
   queries the portal and stuffs the results into a prompt — and "what's been
   visiting the yard this week?" is answered entirely on your LAN, with no
   tokens and no cloud. Note that the MCP server is not built yet; today this
   means a script you write against the portal's read-only API.

2. **Bulk/batch jobs where volume beats brilliance.** Summarizing months of
   detection logs, generating per-species blurbs for the public site, labeling or
   triaging large text sets, drafting doc skeletons. Have Claude Code write the
   script once (it talks to `http://LLMBOX:11434/v1/chat/completions` with the
   `openai` Python client, `base_url` swapped); the box grinds through the volume
   for free. The trade to weigh is per-call cloud cost and rate limits against
   the local model's lower quality: the more times you loop, the more the
   volume argues for local.

3. **Embeddings + semantic search over Orpheus data.** Ollama serves embedding
   models (`nomic-embed-text`, `mxbai-embed-large`). A nightly job embedding
   detection/entity summaries into SQLite (or sqlite-vec) gives you "find nights
   that sounded like this one" — a real Orpheus feature with zero cloud
   dependency, and exactly the kind of enrichment the portal can serve.

4. **A second opinion on a risky diff.** A cheap local pass ("poke holes in
   this") catches a different class of mistake than the model that wrote it.
   Worth wiring as a script that pipes a diff to the endpoint, rather than a
   habit you have to remember.

5. **Dev conveniences with no round trip.** Commit-message drafts from diffs,
   log-line explanation, quick regex help — fast enough locally to be worth it,
   and it keeps your cloud usage for the work that needs the better model.

## Practical setup notes

- Serve Ollama on the LAN: `OLLAMA_HOST=0.0.0.0 ollama serve` on that box — this is
  the real Ollama variable, and it sets the bind address, not the hostname you
  connect to. Verify from your laptop with `curl http://LLMBOX:11434/api/tags`.
- Model picks (as of this writing; check `ollama list` guidance): a ~70B-class
  instruct model for quality chat, an 8–14B for fast batch work, plus one
  embedding model. Pull once, they're cached.
- Keep the API version-pinned in scripts (the OpenAI-compatible endpoint is the
  stable surface).
- If Orpheus code ever calls it, it's a CONSUMER config knob (additive,
  off-by-default, `ollama_url` seam) — same reversibility rules as everything.
