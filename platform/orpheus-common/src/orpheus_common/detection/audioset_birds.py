"""Which AudioSet labels count as "bird-like" — the permissive coverage set.

This answers a *coverage* question — "is this audio-events (PANNs) label
bird-related at all?" — used by the bird-detection parity dashboard to ask
"is audio-events AT LEAST as permissive as BirdNET?". It is intentionally
**broad**: over-including a borderline label is fine; missing a bird is not.

Do not confuse this with the *identity* question in
:mod:`orpheus_common.detection.taxonomy_bridge`. ``same_source`` is
clade-PRECISE (AudioSet ``Crow`` ↔ corvids only) because merging two
detections into one Entity must not be promiscuous. This set is the
permissive SUPERSET used only for coverage scoring — the clade-bridge mids
(``Crow``, ``Caw``) are a subset of it.

Lives in orpheus-common (not the UI backend) so it is a single source of
truth: the UI parity dashboard imports it, and anything else that needs the
"bird-like AudioSet labels" seed can too.
"""

from __future__ import annotations

from typing import Optional

# AudioSet machine_ids that count as "bird-like" for the audio-events vs
# bird-detection parity dashboard. Intentionally permissive — the gating
# decision is "is audio-events AT LEAST as permissive as BirdNET?", so we
# over-include borderline labels rather than miss bird-like detections.
#
# Sourced from the AudioSet ontology under the "Animal sounds" / "Bird"
# subtree. All values verified against the canonical 527-class PANNs CSV
# bundled at agents/orpheus-agent-audio-events/src/orpheus_agent_audio_events/
# data/panns_class_labels_indices.csv. If you add to this list, look the
# display name up in that file to get the right mid AND class index — don't
# guess. Update alongside that CSV.
BIRD_LIKE_AUDIOSET_MIDS: frozenset[str] = frozenset(
    {
        "/m/07qn5dc",    # 101: Crowing, cock-a-doodle-doo (rooster)
        "/m/01rd7k",     # 102: Turkey
        "/m/07svc2k",    # 103: Gobble (turkey vocalization)
        "/m/09ddx",      # 104: Duck
        "/m/07qdb04",    # 105: Quack (duck vocalization)
        "/m/0dbvp",      # 106: Goose
        "/m/07qwf61",    # 107: Honk (goose vocalization)
        "/m/015p6",      # 111: Bird
        "/m/020bb7",     # 112: Bird vocalization, bird call, bird song
        "/m/07pggtn",    # 113: Chirp, tweet
        "/m/07sx8x_",    # 114: Squawk (generic parrot/corvid-like call)
        "/m/0h0rv",      # 115: Pigeon, dove
        "/m/07r_25d",    # 116: Coo  (dove vocalization)
        "/m/04s8yn",     # 117: Crow
        "/m/07r5c2p",    # 118: Caw  (corvid vocalization)
        "/m/09d5_",      # 119: Owl
        "/m/07r_80w",    # 120: Hoot (owl vocalization)
        "/m/05_wcq",     # 121: Bird flight, flapping wings
    }
)


def is_bird_like_audioset_mid(
    species_code: Optional[str], taxonomy_id: Optional[str]
) -> bool:
    """True if a PANNs detection is bird-related, by the permissive seed set.

    Pure membership against :data:`BIRD_LIKE_AUDIOSET_MIDS`. Accepts EITHER a
    ``Detection.species_code`` of the form ``audioset_<mid>`` OR a
    ``TaxonomyRef.id`` of the form ``<mid>``. No DB, no cache — callers that
    want the equivalence-graph-expanded version layer that on top.
    """
    if taxonomy_id and taxonomy_id in BIRD_LIKE_AUDIOSET_MIDS:
        return True
    if species_code and species_code.startswith("audioset_"):
        return species_code[len("audioset_") :] in BIRD_LIKE_AUDIOSET_MIDS
    return False
