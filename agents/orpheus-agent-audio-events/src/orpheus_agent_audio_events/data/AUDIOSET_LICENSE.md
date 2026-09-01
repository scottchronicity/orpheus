# AudioSet Ontology — License & Provenance

The label mapping in `audioset_class_labels_indices.csv` is derived from
the **AudioSet ontology** released by Google Research:

- Paper: Gemmeke et al., *Audio Set: An ontology and human-labeled dataset
  for audio events*, ICASSP 2017.
- Repository: <https://github.com/audioset/ontology>
- Canonical CSV: <https://research.google.com/audioset/dataset/index.html>

**License:** CC BY-SA 4.0 (Creative Commons Attribution-ShareAlike 4.0
International). Attribution requirement is satisfied by this file plus the
links above. Share-alike applies to derivatives of the ontology itself, not
to code or models that consume it.

## About the bundled file

The bundled CSV is a **sparse, hand-curated subset** of the 527-class
ontology, biased toward the categories most relevant to Orpheus's Michigan
wetland deployment (birds, mammals, humans, vehicles, weather, environment).
Indices and machine_ids were transcribed best-effort from publicly available
AudioSet documentation; some entries may be inaccurate or stale.

**For production deployments, replace this file with the canonical 527-row
release** — see the `download-full-audioset-labels` Makefile target (TODO),
or copy `class_labels_indices.csv` from the
[panns_inference release](https://github.com/qiuqiangkong/audioset_tagging_cnn/blob/master/metadata/class_labels_indices.csv).

## Why sparse loading

PANNs emits a 527-dim score vector per frame. The loader (`audioset_ontology.py`)
treats the bundled CSV as a sparse map keyed on class index; indices PANNs
emits that are absent from the CSV are silently dropped in post-processing.
This means the bundled subset → coarser tagging without crashes.

When the canonical file is installed, the same code path produces the full
527-class tagging.
