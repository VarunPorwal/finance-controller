"""The version hash covers what a rule does, not how the YAML was typed.

That is the whole value of the hash: it is stamped on every exception a rule
closed, and a reader who sees the same hash on two runs has to be able to
conclude that the same arithmetic ran. A hash that moved when someone reindented
the file would say nothing, and one that stayed put when a rate changed would
say something false.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from fc.rules.loader import (
    DEFAULT_RULES_PATH,
    RuleSourceError,
    load_rules,
    reload_if_changed,
    ruleset_hash,
    version_hash,
)

_AT = datetime(2026, 8, 29, tzinfo=UTC)

_MINIMAL = """
- id: demo
  version: 1
  name: Demo
  scope:
    counterparty_matches: [BLINKIT]
    date_from: 2026-04-01
  deductions:
    - type: commission
      basis: gross
      rate: 18.0
    - type: gst_on_fee
      basis: commission
      rate: 18.0
  tolerance:
    absolute_paise: 100
    percent: 0.05
"""


def _write(tmp_path: Path, text: str, name: str = "rules.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _load(tmp_path: Path, text: str) -> object:
    return load_rules(_write(tmp_path, text), tenant_id="t_lumea", created_at=_AT)


def test_rates_are_exact_decimals_never_binary_floats(tmp_path: Path) -> None:
    """``Decimal(0.9)`` is 0.9000000000000000222..., and that would be a rate."""
    ruleset = load_rules(
        _write(
            tmp_path,
            _MINIMAL.replace("rate: 18.0", "rate: 0.9", 1),
        ),
        tenant_id="t_lumea",
        created_at=_AT,
    )
    rate = ruleset.rules[0].deductions[0].rate
    assert isinstance(rate, Decimal)
    assert rate == Decimal("0.9")
    assert str(rate) == "0.9"


def test_reformatting_the_file_does_not_move_the_hash(tmp_path: Path) -> None:
    original = load_rules(_write(tmp_path, _MINIMAL, "a.yaml"), tenant_id="t", created_at=_AT)
    reordered = load_rules(
        _write(
            tmp_path,
            """
- name: Renamed, reindented, described
  description: this text decides nothing
  id: demo
  tolerance:
      percent: 0.05
      absolute_paise: 100
  version: 1
  scope:
      date_from: 2026-04-01
      counterparty_matches: [BLINKIT]
  deductions:
      - {type: commission, basis: gross, rate: 18}
      - {type: gst_on_fee, basis: commission, rate: 18.00}
""",
            "b.yaml",
        ),
        tenant_id="t",
        created_at=_AT,
    )
    assert original.rules[0].version_hash == reordered.rules[0].version_hash


def test_changing_a_rate_moves_the_hash(tmp_path: Path) -> None:
    base = load_rules(_write(tmp_path, _MINIMAL, "a.yaml"), tenant_id="t", created_at=_AT)
    changed = load_rules(
        _write(tmp_path, _MINIMAL.replace("rate: 18.0", "rate: 20.0", 1), "b.yaml"),
        tenant_id="t",
        created_at=_AT,
    )
    assert base.rules[0].version_hash != changed.rules[0].version_hash


def test_changing_the_deduction_order_moves_the_hash(tmp_path: Path) -> None:
    """Order is semantics — bases chain — so the hash has to see it."""
    swapped = _MINIMAL.replace(
        """    - type: commission
      basis: gross
      rate: 18.0
    - type: gst_on_fee
      basis: commission
      rate: 18.0""",
        """    - type: gst_on_fee
      basis: gross
      rate: 18.0
    - type: commission
      basis: gross
      rate: 18.0""",
    )
    base = load_rules(_write(tmp_path, _MINIMAL, "a.yaml"), tenant_id="t", created_at=_AT)
    other = load_rules(_write(tmp_path, swapped, "b.yaml"), tenant_id="t", created_at=_AT)
    assert base.rules[0].version_hash != other.rules[0].version_hash


def test_scope_and_tolerance_are_inside_the_hash(tmp_path: Path) -> None:
    base = load_rules(_write(tmp_path, _MINIMAL, "a.yaml"), tenant_id="t", created_at=_AT)
    wider_scope = load_rules(
        _write(tmp_path, _MINIMAL.replace("[BLINKIT]", "[BLINKIT, ZEPTO]"), "b.yaml"),
        tenant_id="t",
        created_at=_AT,
    )
    looser_tolerance = load_rules(
        _write(
            tmp_path, _MINIMAL.replace("absolute_paise: 100", "absolute_paise: 10000"), "c.yaml"
        ),
        tenant_id="t",
        created_at=_AT,
    )
    hashes = {
        base.rules[0].version_hash,
        wider_scope.rules[0].version_hash,
        looser_tolerance.rules[0].version_hash,
    }
    assert len(hashes) == 3


def test_the_tenant_is_not_inside_the_hash(tmp_path: Path) -> None:
    """Two merchants on the same terms run the same arithmetic, and should say so."""
    path = _write(tmp_path, _MINIMAL)
    one = load_rules(path, tenant_id="t_lumea", created_at=_AT)
    two = load_rules(path, tenant_id="t_other", created_at=_AT)
    assert one.rules[0].version_hash == two.rules[0].version_hash


def test_the_ruleset_hash_ignores_the_order_rules_appear_in(tmp_path: Path) -> None:
    two_rules = _MINIMAL + _MINIMAL.replace("id: demo", "id: other")
    reversed_file = _MINIMAL.replace("id: demo", "id: other") + _MINIMAL
    first = load_rules(_write(tmp_path, two_rules, "a.yaml"), tenant_id="t", created_at=_AT)
    second = load_rules(_write(tmp_path, reversed_file, "b.yaml"), tenant_id="t", created_at=_AT)
    assert first.ruleset_hash == second.ruleset_hash
    assert first.ruleset_hash == ruleset_hash(second.rules)


def test_effective_dates_default_from_the_scope_window(tmp_path: Path) -> None:
    ruleset = _load(tmp_path, _MINIMAL)
    rule = ruleset.rules[0]  # type: ignore[attr-defined]
    assert rule.effective_from == date(2026, 4, 1)
    assert rule.effective_to is None


def test_a_file_stating_two_different_effective_dates_is_refused(tmp_path: Path) -> None:
    """A rule with two effective_from dates has none."""
    with pytest.raises(RuleSourceError, match="disagrees with scope.date_from"):
        _load(tmp_path, _MINIMAL + "  effective_from: 2026-07-01\n")


def test_a_basis_naming_a_later_deduction_is_refused_at_load(tmp_path: Path) -> None:
    text = _MINIMAL.replace(
        """    - type: commission
      basis: gross
      rate: 18.0
    - type: gst_on_fee
      basis: commission
      rate: 18.0""",
        """    - type: gst_on_fee
      basis: commission
      rate: 18.0
    - type: commission
      basis: gross
      rate: 18.0""",
    )
    with pytest.raises(RuleSourceError, match="is not gross, net, or a deduction computed"):
        _load(tmp_path, text)


def test_a_deduction_type_computed_twice_is_refused(tmp_path: Path) -> None:
    """The second would overwrite the basis the first published."""
    text = _MINIMAL.replace("type: gst_on_fee", "type: commission")
    with pytest.raises(RuleSourceError, match="computed twice"):
        _load(tmp_path, text)


def test_rates_totalling_more_than_the_gross_are_refused(tmp_path: Path) -> None:
    """A rule that explains more money than existed is a way to close anything."""
    text = _MINIMAL.replace(
        "rate: 18.0\n    - type: gst_on_fee", "rate: 90.0\n    - type: gst_on_fee"
    )
    text = text.replace("basis: commission\n      rate: 18.0", "basis: gross\n      rate: 30.0")
    with pytest.raises(RuleSourceError, match="more than 100% of gross"):
        _load(tmp_path, text)


def test_the_same_rule_version_declared_twice_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuleSourceError, match="declared twice"):
        _load(tmp_path, _MINIMAL + _MINIMAL)


def test_an_unknown_top_level_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuleSourceError, match="unknown key"):
        _load(tmp_path, _MINIMAL + "  auto_close: true\n")


def test_an_unknown_scope_key_is_refused(tmp_path: Path) -> None:
    """``Scope`` forbids extras, so a typo cannot silently widen a rule."""
    with pytest.raises(RuleSourceError, match="invalid scope"):
        _load(tmp_path, _MINIMAL.replace("date_from:", "date_form:"))


def test_a_missing_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuleSourceError, match="'id' is required"):
        _load(tmp_path, _MINIMAL.replace("- id: demo", "- version: 1"))


def test_hot_reload_returns_the_same_object_when_nothing_changed(tmp_path: Path) -> None:
    path = _write(tmp_path, _MINIMAL)
    ruleset = load_rules(path, tenant_id="t", created_at=_AT)
    assert reload_if_changed(ruleset, tenant_id="t", created_at=_AT) is ruleset


def test_hot_reload_picks_up_an_edited_file(tmp_path: Path) -> None:
    path = _write(tmp_path, _MINIMAL)
    ruleset = load_rules(path, tenant_id="t", created_at=_AT)
    path.write_text(_MINIMAL.replace("rate: 18.0", "rate: 20.0", 1), encoding="utf-8")
    reloaded = reload_if_changed(ruleset, tenant_id="t", created_at=_AT)
    assert reloaded is not ruleset
    assert reloaded.rules[0].deductions[0].rate == Decimal("20")
    assert reloaded.ruleset_hash != ruleset.ruleset_hash


def test_the_ruleset_hash_is_stable_across_checkouts(tmp_path: Path) -> None:
    """Mtimes differ between checkouts; the hash must not."""
    first = load_rules(_write(tmp_path, _MINIMAL, "a.yaml"), tenant_id="t", created_at=_AT)
    second = load_rules(_write(tmp_path, _MINIMAL, "b.yaml"), tenant_id="t", created_at=_AT)
    assert first.ruleset_hash == second.ruleset_hash
    assert first.fingerprint != second.fingerprint


def test_version_hash_is_callable_without_a_file() -> None:
    """The API creates rules from JSON; hashing must not require YAML on disk."""
    ruleset = load_rules(DEFAULT_RULES_PATH, tenant_id="t", created_at=_AT)
    rule = ruleset.by_id("blinkit_commission")[0]
    assert version_hash(rule.scope, rule.deductions, rule.tolerance) == rule.version_hash
