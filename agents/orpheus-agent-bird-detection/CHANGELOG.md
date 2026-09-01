# Changelog

## 0.2.0 — 2026-08-25

- Runs on the Actor base.
- Uses sigmoid on multi-label logits instead of softmax, so simultaneous species are no longer collapsed into one, and de-duplicates windows by label index.
- Geographic plausibility filter with a site whitelist and a soft-admit path for rare-but-real visitors.
- Database save failures are counted on the error feed instead of being swallowed; the recovery instruction names a command that exists.
