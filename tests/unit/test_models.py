"""The domain model contract: field names, category set, determinism, isolation.

Field names are load-bearing. The SQLAlchemy tables, the Alembic migration and
the generated TypeScript client all key off them, so a rename that slips through
here breaks the schema freeze (PRD §0.4).
"""

from __future__ import annotations

import typing
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fc.models import (
    AUTO_SAFE,
    CUT_VERBS,
    NEVER_AUTO,
    READ_ONLY_VERBS,
    WRITE_VERBS,
    CommandVerb,
    ExceptionCategory,
    MatchEvidence,
    MatchResult,
    TransactionEvent,
    deterministic_factory,
    new_ulid,
)

# PRD §4.2, in order.
EXPECTED_FIELDS = (
    "event_id",
    "run_id",
    "tenant_id",
    "source",
    "source_row_id",
    "amount_paise",
    "direction",
    "currency",
    "txn_date",
    "value_date",
    "settled_at",
    "utr",
    "rrn",
    "settlement_id",
    "order_id",
    "payment_id",
    "voucher_number",
    "voucher_guid",
    "counterparty",
    "counterparty_norm",
    "method",
    "rail",
    "txn_type",
    "raw_narration",
    "fee_paise",
    "tax_paise",
    "on_hold",
    "ledger_account",
    "voucher_type",
    "raw",
    "ingested_at",
    "gt_match_group",
    "gt_label",
)


def _event(**overrides: object) -> TransactionEvent:
    base: dict[str, object] = {
        "event_id": "evt_1",
        "run_id": "run_1",
        "tenant_id": "t_lumea",
        "source": "razorpay",
        "source_row_id": "pay_MkQ8vLp2",
        "amount_paise": 96578,
        "direction": "credit",
        "txn_date": date(2026, 8, 14),
        "raw": {"entity_id": "pay_MkQ8vLp2"},
        "ingested_at": datetime(2026, 8, 15, 6, 0, tzinfo=UTC),
    }
    return TransactionEvent(**(base | overrides))  # type: ignore[arg-type]


def test_transaction_event_field_names_match_prd() -> None:
    assert tuple(TransactionEvent.model_fields) == EXPECTED_FIELDS


def test_amount_paise_is_int_not_float() -> None:
    assert TransactionEvent.model_fields["amount_paise"].annotation is int


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        _event(amount_paise_typo=1)


def test_ground_truth_is_strippable() -> None:
    event = _event(gt_match_group="grp_1", gt_label="matched_exact")
    assert event.without_ground_truth().gt_match_group is None
    assert event.without_ground_truth().gt_label is None


def test_effective_date_prefers_value_date() -> None:
    assert _event().effective_date == date(2026, 8, 14)
    assert _event(value_date=date(2026, 8, 16)).effective_date == date(2026, 8, 16)


def test_exception_categories_cover_the_classification_tree() -> None:
    categories = set(typing.get_args(ExceptionCategory))
    assert len(categories) == 12
    assert AUTO_SAFE <= categories
    assert NEVER_AUTO <= categories
    assert not AUTO_SAFE & NEVER_AUTO
    assert "unknown" in NEVER_AUTO


def test_command_verbs_partition_into_write_and_read_only() -> None:
    verbs = set(typing.get_args(CommandVerb))
    assert len(verbs) == 14
    assert WRITE_VERBS | READ_ONLY_VERBS == verbs
    assert not WRITE_VERBS & READ_ONLY_VERBS
    assert CUT_VERBS <= verbs


def test_match_requires_evidence() -> None:
    """Nothing closes without evidence: empty evidence is a bug (hard rule 5)."""
    with pytest.raises(ValidationError):
        MatchResult(
            match_id="m_1",
            run_id="run_1",
            tenant_id="t_lumea",
            group_key="grp_1",
            event_ids=["evt_1"],
            sources_covered=["razorpay"],
            stage="exact_ref",
            confidence=Decimal("1.0"),
            evidence=[],
            created_at=datetime(2026, 8, 15, tzinfo=UTC),
        )


def test_match_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        MatchResult(
            match_id="m_1",
            run_id="run_1",
            tenant_id="t_lumea",
            group_key="grp_1",
            event_ids=["evt_1"],
            sources_covered=["razorpay"],
            stage="exact_ref",
            confidence=Decimal("1.5"),
            evidence=[MatchEvidence(stage="exact_ref")],
            created_at=datetime(2026, 8, 15, tzinfo=UTC),
        )


def test_ulid_is_sortable_and_deterministic_under_a_seed() -> None:
    first = deterministic_factory(42, 1_756_339_200_000)
    second = deterministic_factory(42, 1_756_339_200_000)
    left = [first("evt_") for _ in range(20)]
    right = [second("evt_") for _ in range(20)]
    assert left == right
    assert left == sorted(left)
    assert len(set(left)) == 20


def test_ulid_default_path_is_26_chars() -> None:
    assert len(new_ulid()) == 26
    assert new_ulid("run_").startswith("run_")
