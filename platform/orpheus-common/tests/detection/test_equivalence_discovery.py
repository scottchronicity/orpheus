"""Tests for the auto-discovery worker — Layer 3 follow-up.

Validates that observing real co-occurrence patterns over time produces
the right equivalence proposals:

  - High co-occurrence → auto-accepted equivalence
  - Medium co-occurrence → pending_review
  - Low / one-off co-occurrence → skipped
  - Existing equivalences not re-proposed
  - Non-equivalence rows block proposals
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orpheus_common.detection import (
    Detection,
    DetectionDB,
    TaxonomyEquivalenceDB,
    TaxonomyRef,
    discover_equivalences,
)


@pytest.fixture
def db(tmp_path: Path) -> DetectionDB:
    return DetectionDB(db_path=tmp_path / "detections.db")


@pytest.fixture
def eq_db(tmp_path: Path) -> TaxonomyEquivalenceDB:
    return TaxonomyEquivalenceDB(db_path=tmp_path / "equivalence.db")


def _make_detection(
    db: DetectionDB,
    *,
    event_id: str,
    root_event_id: str,
    taxonomy: TaxonomyRef,
    timestamp: datetime,
    detection_type: str = "species.detected",
) -> None:
    """Insert a Detection with the given taxonomy + chain root."""
    det = Detection(
        event_id=event_id,
        timestamp=timestamp,
        detection_type=detection_type,
        species_code=f"{taxonomy.namespace}_{taxonomy.id}",
        taxonomy=taxonomy,
        root_event_id=root_event_id,
        confidence=0.9,
    )
    db.save(det)


def _crow_ioc() -> TaxonomyRef:
    return TaxonomyRef(namespace="ioc", id="Corvus brachyrhynchos")


def _crow_audioset() -> TaxonomyRef:
    return TaxonomyRef(namespace="audioset", id="/m/04s8yn")


def _robin_ioc() -> TaxonomyRef:
    return TaxonomyRef(namespace="ioc", id="Turdus migratorius")


class TestHighCooccurrenceAutoAccepts:
    """When two TaxonomyRefs fire together on most events, the
    Jaccard is high → auto-accepted equivalence row written."""

    def test_perfect_overlap_proposes_at_high_confidence(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # 10 audio.motion events. On every single one, both BirdNET
        # (ioc:Corvus brachyrhynchos) and PANNs (audioset:/m/04s8yn) fire.
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = now - timedelta(hours=i)
            root = f"am-{i:03d}"
            _make_detection(
                db,
                event_id=f"bd-{i:03d}",
                root_event_id=root,
                taxonomy=_crow_ioc(),
                timestamp=ts,
                detection_type="species.detected",
            )
            _make_detection(
                db,
                event_id=f"ae-{i:03d}",
                root_event_id=root,
                taxonomy=_crow_audioset(),
                timestamp=ts,
                detection_type="audio.classified",
            )

        proposals = discover_equivalences(
            db,
            eq_db,
            lookback_days=30,
            min_cooccurrences=2,  # lower for tests
        )

        # Should propose one pair, auto-accepted.
        assert len(proposals) == 1
        prop = proposals[0]
        assert prop["jaccard"] == 1.0
        assert prop["status"] == "accepted"
        assert prop["action"] == "recorded"
        assert prop["cooccurrence"] == 10

        # The equivalence is now active in the graph.
        assert eq_db.is_equivalent(_crow_ioc(), _crow_audioset()) is True


class TestMediumCooccurrenceProposes:
    """Jaccard in [propose, accept) lands as pending_review and does NOT
    immediately affect equivalent_taxa queries."""

    def test_jaccard_75_pct_pending_review(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # 8 events; BirdNET on all 8; PANNs on 6 of those (different mix).
        now = datetime.now(timezone.utc)
        for i in range(8):
            ts = now - timedelta(hours=i)
            root = f"am-{i:03d}"
            _make_detection(
                db,
                event_id=f"bd-{i:03d}",
                root_event_id=root,
                taxonomy=_crow_ioc(),
                timestamp=ts,
            )
            if i < 6:
                _make_detection(
                    db,
                    event_id=f"ae-{i:03d}",
                    root_event_id=root,
                    taxonomy=_crow_audioset(),
                    timestamp=ts,
                    detection_type="audio.classified",
                )

        proposals = discover_equivalences(
            db,
            eq_db,
            lookback_days=30,
            min_cooccurrences=2,
            propose_threshold=0.6,
            accept_threshold=0.9,
        )
        assert len(proposals) == 1
        prop = proposals[0]
        # Jaccard = 6 / 8 = 0.75 → pending_review.
        assert prop["jaccard"] == pytest.approx(0.75, abs=0.001)
        assert prop["status"] == "pending_review"
        # is_equivalent is False until the proposal is accepted by a human.
        assert eq_db.is_equivalent(_crow_ioc(), _crow_audioset()) is False
        # But it's visible in the review queue.
        pending = eq_db.list_pending_review()
        assert len(pending) == 1


class TestLowCooccurrenceIgnored:
    """One-off co-occurrence below the propose threshold gets dropped."""

    def test_below_threshold_not_proposed(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # 100 BirdNET events for ioc:Corvus, only 2 of which also have
        # PANNs audio.classified for /m/04s8yn. Jaccard = 2/100 = 0.02
        # — well below propose threshold.
        now = datetime.now(timezone.utc)
        for i in range(100):
            ts = now - timedelta(minutes=i)
            root = f"am-{i:03d}"
            _make_detection(
                db, event_id=f"bd-{i:03d}", root_event_id=root,
                taxonomy=_crow_ioc(), timestamp=ts,
            )
            if i < 2:
                _make_detection(
                    db, event_id=f"ae-{i:03d}", root_event_id=root,
                    taxonomy=_crow_audioset(), timestamp=ts,
                    detection_type="audio.classified",
                )

        proposals = discover_equivalences(
            db, eq_db, lookback_days=30,
            min_cooccurrences=2,  # lower than test's 2 cooccurrences
        )
        # Even though min_cooccurrences (2) is met, the jaccard 0.02 is
        # below propose_threshold (0.6) → no proposal.
        assert len(proposals) == 0


class TestMinCooccurrencesFilter:
    """Very small samples are filtered by min_cooccurrences regardless of
    Jaccard — prevents proposing equivalences from too little data."""

    def test_single_cooccurrence_blocked_by_min_count(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # Both fire on exactly 1 event together. Jaccard = 1.0 (each fires
        # only once, together) but min_cooccurrences=5 blocks the proposal.
        now = datetime.now(timezone.utc)
        _make_detection(
            db, event_id="bd-1", root_event_id="am-1", taxonomy=_crow_ioc(),
            timestamp=now,
        )
        _make_detection(
            db, event_id="ae-1", root_event_id="am-1", taxonomy=_crow_audioset(),
            timestamp=now, detection_type="audio.classified",
        )

        proposals = discover_equivalences(
            db, eq_db, lookback_days=30, min_cooccurrences=5,
        )
        assert len(proposals) == 0


class TestSkipsExistingEquivalence:
    """Pairs already in taxonomy_equivalence don't get re-proposed."""

    def test_existing_pair_marked_skipped(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # Pre-record the equivalence manually.
        eq_db.record_equivalence(_crow_ioc(), _crow_audioset(), source="manual")

        # Then generate co-occurrence data — auto-discovery should skip.
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = now - timedelta(hours=i)
            root = f"am-{i:03d}"
            _make_detection(
                db, event_id=f"bd-{i:03d}", root_event_id=root,
                taxonomy=_crow_ioc(), timestamp=ts,
            )
            _make_detection(
                db, event_id=f"ae-{i:03d}", root_event_id=root,
                taxonomy=_crow_audioset(), timestamp=ts,
                detection_type="audio.classified",
            )

        proposals = discover_equivalences(
            db, eq_db, lookback_days=30, min_cooccurrences=2,
        )
        assert len(proposals) == 1
        assert proposals[0]["action"] == "skipped_existing"


class TestPromotesPendingReview:
    """A pending_review pair should get promoted to accepted on a
    later run when fresh evidence pushes Jaccard above the
    auto-accept threshold."""

    def test_pending_promoted_when_jaccard_crosses_accept_threshold(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # Pre-record the equivalence as pending_review with a stale
        # low confidence (as if a prior weak-evidence run wrote it).
        eq_db.record_equivalence(
            _crow_ioc(),
            _crow_audioset(),
            confidence=0.65,
            source="auto_discovered",
            status="pending_review",
        )

        # Now generate strong co-occurrence evidence (10 events both
        # taxa appear in → Jaccard = 1.0, well above the default
        # accept_threshold).
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = now - timedelta(hours=i)
            root = f"am-{i:03d}"
            _make_detection(
                db, event_id=f"bd-{i:03d}", root_event_id=root,
                taxonomy=_crow_ioc(), timestamp=ts,
            )
            _make_detection(
                db, event_id=f"ae-{i:03d}", root_event_id=root,
                taxonomy=_crow_audioset(), timestamp=ts,
                detection_type="audio.classified",
            )

        proposals = discover_equivalences(
            db, eq_db, lookback_days=30, min_cooccurrences=2,
        )
        assert len(proposals) == 1
        # The pair was pending and now Jaccard >= accept_threshold →
        # it should be promoted to accepted, not skipped_existing.
        assert proposals[0]["action"] == "promoted"
        assert proposals[0]["status"] == "accepted"

        # The row in the DB should now reflect the accepted status.
        assert eq_db.is_equivalent(_crow_ioc(), _crow_audioset())

    def test_pending_not_promoted_when_jaccard_still_below_threshold(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # Pre-record at pending_review with low confidence.
        eq_db.record_equivalence(
            _crow_ioc(),
            _crow_audioset(),
            confidence=0.5,
            source="auto_discovered",
            status="pending_review",
        )

        # New evidence is still moderate (Jaccard ~0.5, below
        # accept_threshold) — should be skipped, NOT churned with a new
        # write on every run.
        now = datetime.now(timezone.utc)
        for i in range(4):
            ts = now - timedelta(hours=i)
            root = f"am-{i:03d}"
            _make_detection(
                db, event_id=f"bd-{i:03d}", root_event_id=root,
                taxonomy=_crow_ioc(), timestamp=ts,
            )
            _make_detection(
                db, event_id=f"ae-{i:03d}", root_event_id=root,
                taxonomy=_crow_audioset(), timestamp=ts,
                detection_type="audio.classified",
            )
        # An unrelated event with only crow_ioc to push the Jaccard
        # below 1.0 (4 cooc / (5 + 4) = ~0.44).
        _make_detection(
            db, event_id="bd-solo", root_event_id="am-solo",
            taxonomy=_crow_ioc(), timestamp=now - timedelta(hours=10),
        )

        proposals = discover_equivalences(
            db, eq_db, lookback_days=30, min_cooccurrences=2,
            accept_threshold=0.9, propose_threshold=0.3,
        )
        if proposals:
            # If proposed at all, it must be skipped (still pending);
            # NOT re-recorded.
            assert proposals[0]["action"] == "skipped_existing"


class TestNonEquivalenceBlocks:
    """A taxonomy_non_equivalence row blocks auto-discovery from
    re-proposing the same pair."""

    def test_blocked_pair_marked_skipped(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # Explicitly assert non-equivalence.
        eq_db.record_non_equivalence(_crow_ioc(), _crow_audioset(), source="manual")

        # Now generate co-occurrence — should be blocked.
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = now - timedelta(hours=i)
            root = f"am-{i:03d}"
            _make_detection(
                db, event_id=f"bd-{i:03d}", root_event_id=root,
                taxonomy=_crow_ioc(), timestamp=ts,
            )
            _make_detection(
                db, event_id=f"ae-{i:03d}", root_event_id=root,
                taxonomy=_crow_audioset(), timestamp=ts,
                detection_type="audio.classified",
            )

        proposals = discover_equivalences(
            db, eq_db, lookback_days=30, min_cooccurrences=2,
        )
        assert len(proposals) == 1
        assert proposals[0]["action"] == "skipped_blocked"
        # Non-equivalence still holds.
        assert eq_db.is_equivalent(_crow_ioc(), _crow_audioset()) is False


class TestUnrelatedTaxaNotMerged:
    """TaxonomyRefs that DON'T co-occur enough remain unrelated."""

    def test_crow_and_robin_stay_separate(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # Crow fires on 10 events. Robin fires on a completely different
        # set of 10 events. Zero co-occurrence.
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = now - timedelta(hours=i)
            _make_detection(
                db, event_id=f"crow-{i}", root_event_id=f"am-crow-{i}",
                taxonomy=_crow_ioc(), timestamp=ts,
            )
        for i in range(10):
            ts = now - timedelta(hours=20 + i)  # different time, different event
            _make_detection(
                db, event_id=f"robin-{i}", root_event_id=f"am-robin-{i}",
                taxonomy=_robin_ioc(), timestamp=ts,
            )

        proposals = discover_equivalences(
            db, eq_db, lookback_days=30, min_cooccurrences=2,
        )
        assert len(proposals) == 0
        assert eq_db.is_equivalent(_crow_ioc(), _robin_ioc()) is False


class TestLookbackWindow:
    """Co-occurrences outside the lookback window are ignored."""

    def test_old_data_outside_window_not_counted(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # 5 events 30 days ago (outside default 7-day window).
        old = datetime.now(timezone.utc) - timedelta(days=30)
        for i in range(5):
            ts = old - timedelta(hours=i)
            root = f"am-old-{i}"
            _make_detection(
                db, event_id=f"old-bd-{i}", root_event_id=root,
                taxonomy=_crow_ioc(), timestamp=ts,
            )
            _make_detection(
                db, event_id=f"old-ae-{i}", root_event_id=root,
                taxonomy=_crow_audioset(), timestamp=ts,
                detection_type="audio.classified",
            )

        proposals = discover_equivalences(
            db, eq_db, lookback_days=7, min_cooccurrences=2,
        )
        # Data is outside the 7-day window → no proposals.
        assert len(proposals) == 0


class TestCrossNamespaceAcceptGuard:
    """The same-namespace safety guard. Two ioc species that merely co-occur
    (dawn-chorus crow + robin) must not auto-merge into one Entity when
    ``cross_namespace_accept_only=True`` — co-occurrence is not identity."""

    def _seed_same_namespace_perfect_overlap(self, db: DetectionDB) -> None:
        # Crow (ioc) and Robin (ioc) fire together on all 10 events: perfect
        # Jaccard, but two genuinely distinct species in the SAME namespace.
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = now - timedelta(hours=i)
            root = f"am-{i:03d}"
            _make_detection(
                db, event_id=f"crow-{i:03d}", root_event_id=root,
                taxonomy=_crow_ioc(), timestamp=ts,
            )
            _make_detection(
                db, event_id=f"robin-{i:03d}", root_event_id=root,
                taxonomy=_robin_ioc(), timestamp=ts,
            )

    def test_same_namespace_auto_accepts_by_default(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # Default (guard off) preserves the historical behaviour exactly — a
        # same-namespace perfect-overlap pair auto-accepts. This is the bug the
        # guard fixes; keeping the default put is what makes the change
        # reversible (off-by-default flag).
        self._seed_same_namespace_perfect_overlap(db)
        proposals = discover_equivalences(
            db, eq_db, lookback_days=30, min_cooccurrences=2
        )
        assert len(proposals) == 1
        assert proposals[0]["status"] == "accepted"
        assert eq_db.is_equivalent(_crow_ioc(), _robin_ioc()) is True

    def test_same_namespace_capped_at_pending_when_guard_on(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        self._seed_same_namespace_perfect_overlap(db)
        proposals = discover_equivalences(
            db, eq_db, lookback_days=30, min_cooccurrences=2,
            cross_namespace_accept_only=True,
        )
        assert len(proposals) == 1
        prop = proposals[0]
        assert prop["jaccard"] == 1.0
        # Demoted: recorded for human review, NOT auto-accepted/merged.
        assert prop["status"] == "pending_review"
        assert prop["action"] == "recorded"
        assert eq_db.is_equivalent(_crow_ioc(), _robin_ioc()) is False
        # It IS still surfaced in the review queue for a human.
        assert len(eq_db.list_pending_review()) == 1

    def test_cross_namespace_still_auto_accepts_with_guard_on(
        self, db: DetectionDB, eq_db: TaxonomyEquivalenceDB
    ) -> None:
        # The guard must NOT block the legitimate case: two classifiers naming
        # the same source (ioc crow ↔ audioset crow) still auto-accept.
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = now - timedelta(hours=i)
            root = f"am-{i:03d}"
            _make_detection(
                db, event_id=f"bd-{i:03d}", root_event_id=root,
                taxonomy=_crow_ioc(), timestamp=ts,
            )
            _make_detection(
                db, event_id=f"ae-{i:03d}", root_event_id=root,
                taxonomy=_crow_audioset(), timestamp=ts,
                detection_type="audio.classified",
            )
        proposals = discover_equivalences(
            db, eq_db, lookback_days=30, min_cooccurrences=2,
            cross_namespace_accept_only=True,
        )
        assert len(proposals) == 1
        assert proposals[0]["status"] == "accepted"
        assert eq_db.is_equivalent(_crow_ioc(), _crow_audioset()) is True
