"""Rule loading, semantic hashing and hot reload — PRD Appendix D, §4.3.6.

A rule version is identified by ``version_hash``, and the hash covers **what the
rule does** — scope, deductions, tolerance — not how the YAML happened to be
written. Reindenting the file, reordering mapping keys or rewording
``description`` leaves the hash alone; changing a rate does not. That is what
makes the hash usable as the provenance stamp on a closed exception: two runs
that report the same hash really did apply the same arithmetic.

**Floats never enter.** ``yaml.safe_load`` turns ``rate: 18.0`` into a binary
float, and ``Decimal(0.9)`` is ``0.90000000000000002220446...``. The loader
registers a constructor that builds a ``Decimal`` from the scalar's own source
text instead, so a rate is exact from the moment it is read. Pydantic never sees
a float and the AST money scan over ``fc/rules`` stays true rather than
technically true.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from fc.models.rule import Deduction, Rule, Scope, Tolerance

__all__ = [
    "DEFAULT_RULES_PATH",
    "RuleSet",
    "RuleSourceError",
    "canonical_semantics",
    "load_rules",
    "reload_if_changed",
    "ruleset_hash",
    "version_hash",
]

# engine/src/fc/rules/loader.py -> repo root is four parents up.
DEFAULT_RULES_PATH = Path(__file__).resolve().parents[4] / "data" / "rules" / "deductions.yaml"

_FLOAT_TAG = "tag:yaml.org,2002:float"

#: Reference gross used to test that a rule's *rate* portion cannot exceed the
#: money it is deducted from. Rates are linear in gross, so one probe settles it
#: for every gross; ₹10,00,000 is large enough that per-line paise rounding
#: cannot flip the comparison.
_BOUND_PROBE_PAISE = 10_00_000_00

_HASH_PREFIX_LENGTH = 16


class RuleSourceError(ValueError):
    """A rules file that cannot be trusted. Raised at load, never at apply time."""


class _DecimalSafeLoader(yaml.SafeLoader):
    """``SafeLoader`` with YAML floats constructed as exact ``Decimal``."""


def _decimal_from_scalar(loader: yaml.SafeLoader, node: yaml.Node) -> Decimal:
    return Decimal(loader.construct_scalar(node))  # type: ignore[arg-type]


_DecimalSafeLoader.add_constructor(_FLOAT_TAG, _decimal_from_scalar)


@dataclass(frozen=True)
class RuleSet:
    """Every rule one file declares, plus what it was loaded from.

    ``fingerprint`` is the ``(path, mtime_ns, size)`` of each source file and is
    the only thing :func:`reload_if_changed` compares. It is deliberately not
    part of :attr:`ruleset_hash`: two checkouts of the same YAML must produce the
    same ruleset hash, and file mtimes differ between checkouts.
    """

    rules: tuple[Rule, ...]
    ruleset_hash: str
    sources: tuple[Path, ...]
    fingerprint: tuple[tuple[str, int, int], ...]

    def active_on(self, on_date: date) -> tuple[Rule, ...]:
        """Rules with ``status == 'active'`` whose effective window covers ``on_date``."""
        return tuple(
            rule
            for rule in self.rules
            if rule.status == "active"
            and rule.effective_from <= on_date
            and (rule.effective_to is None or on_date <= rule.effective_to)
        )

    def by_id(self, rule_id: str) -> tuple[Rule, ...]:
        """Every version of one rule, oldest first."""
        return tuple(
            sorted((r for r in self.rules if r.rule_id == rule_id), key=lambda r: r.version)
        )


def canonical_semantics(scope: Scope, deductions: Sequence[Deduction], tolerance: Tolerance) -> str:
    """The exact bytes :func:`version_hash` digests.

    Exposed so a disagreement about two hashes can be diffed rather than
    guessed at. Deduction order is preserved because order is significant —
    ``gst_on_fee`` before ``commission`` computes a different number — while
    scope keys are sorted because a mapping has no order to preserve.
    """
    payload = {
        "scope": {
            key: _plain(value) for key, value in sorted(scope.model_dump(exclude_none=True).items())
        },
        "deductions": [
            {
                "type": d.type,
                "basis": d.basis,
                "rate": _decimal_text(d.rate),
                "fixed_paise": d.fixed_paise or 0,
            }
            for d in deductions
        ],
        "tolerance": {
            "absolute_paise": tolerance.absolute_paise,
            "percent": _decimal_text(tolerance.percent),
        },
    }
    return json.dumps(payload, sort_keys=False, separators=(",", ":"), ensure_ascii=False)


def version_hash(scope: Scope, deductions: Sequence[Deduction], tolerance: Tolerance) -> str:
    """SHA-256 over the semantic content of one rule version."""
    return hashlib.sha256(canonical_semantics(scope, deductions, tolerance).encode()).hexdigest()


def ruleset_hash(rules: Iterable[Rule]) -> str:
    """A single hash over a whole ruleset, for ``runs.ruleset_hash``.

    Sorted by ``(rule_id, version)`` so the order rules appear in the file
    cannot change it: the ruleset is a set, and the run stamp must say which
    arithmetic was available, not how it was typed.
    """
    digest = hashlib.sha256()
    for rule in sorted(rules, key=lambda r: (r.rule_id, r.version)):
        digest.update(f"{rule.rule_id}:{rule.version}:{rule.version_hash}\n".encode())
    return digest.hexdigest()


def load_rules(
    path: Path | str = DEFAULT_RULES_PATH,
    *,
    tenant_id: str,
    created_at: datetime,
    default_status: str = "active",
) -> RuleSet:
    """Load and validate one Appendix D rules file.

    ``created_at`` is supplied rather than read from the clock: loading the same
    file twice must produce identical ``Rule`` objects, and a wall-clock read in
    a load path is a determinism bug waiting for a slow disk (hard rule 9).
    """
    source = Path(path)
    try:
        raw_text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuleSourceError(f"cannot read rules file {source}: {exc}") from exc

    documents = yaml.load(raw_text, Loader=_DecimalSafeLoader)
    if documents is None:
        documents = []
    if not isinstance(documents, list):
        raise RuleSourceError(
            f"{source}: expected a YAML list of rules, got {type(documents).__name__}"
        )

    rules = tuple(
        _build_rule(entry, index, source, tenant_id, created_at, default_status)
        for index, entry in enumerate(documents)
    )
    _reject_duplicate_versions(rules, source)
    stat = source.stat()
    return RuleSet(
        rules=rules,
        ruleset_hash=ruleset_hash(rules),
        sources=(source,),
        fingerprint=((str(source), stat.st_mtime_ns, stat.st_size),),
    )


def reload_if_changed(ruleset: RuleSet, **kwargs: Any) -> RuleSet:
    """Re-read the sources only when one of them has actually changed.

    The customer edits their rulebook while the API is up; the API must pick it
    up without a restart and must not re-parse on every request. Returns the
    same object when nothing moved, so an identity check is a valid staleness
    test at the call site.
    """
    for name, mtime_ns, size in ruleset.fingerprint:
        try:
            stat = Path(name).stat()
        except OSError:
            break
        if stat.st_mtime_ns != mtime_ns or stat.st_size != size:
            break
    else:
        return ruleset
    return load_rules(ruleset.sources[0], **kwargs)


def _build_rule(
    entry: object,
    index: int,
    source: Path,
    tenant_id: str,
    created_at: datetime,
    default_status: str,
) -> Rule:
    where = f"{source}[{index}]"
    if not isinstance(entry, dict):
        raise RuleSourceError(f"{where}: expected a mapping, got {type(entry).__name__}")

    body = dict(entry)
    rule_id = body.pop("id", None)
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise RuleSourceError(f"{where}: 'id' is required and must be a non-empty string")

    scope = _build_scope(body.pop("scope", None), where)
    deductions = _build_deductions(body.pop("deductions", None), where)
    tolerance = _build_tolerance(body.pop("tolerance", None), where)
    _reject_unbounded_stack(deductions, where)

    effective_from = _as_date(body.pop("effective_from", None), where, "effective_from")
    effective_to = _as_date(body.pop("effective_to", None), where, "effective_to")
    # Appendix D dates the scope; §4.3.6 dates the row. They are the same window
    # written in two places, so the loader derives one from the other and refuses
    # a file that states both and disagrees - a rule with two effective_from
    # dates has none.
    if effective_from is None:
        effective_from = scope.date_from
    elif effective_from != scope.date_from:
        raise RuleSourceError(
            f"{where}: effective_from {effective_from} disagrees with scope.date_from "
            f"{scope.date_from}; a rule has one effective window"
        )
    if effective_to is None:
        effective_to = scope.date_to
    elif effective_to != scope.date_to:
        raise RuleSourceError(
            f"{where}: effective_to {effective_to} disagrees with scope.date_to {scope.date_to}"
        )
    if effective_to is not None and effective_to < effective_from:
        raise RuleSourceError(f"{where}: effective_to {effective_to} precedes {effective_from}")

    unknown = sorted(set(body) - _RULE_KEYS)
    if unknown:
        raise RuleSourceError(f"{where}: unknown key(s) {unknown}")

    return Rule(
        rule_id=rule_id,
        version=_as_int(body.get("version", 1), where, "version"),
        tenant_id=tenant_id,
        version_hash=version_hash(scope, deductions, tolerance),
        name=str(body.get("name", rule_id)),
        description=_as_optional_str(body.get("description")),
        scope=scope,
        deductions=list(deductions),
        tolerance=tolerance,
        priority=_as_int(body.get("priority", 100), where, "priority"),
        effective_confidence=_as_decimal(
            body.get("effective_confidence", Decimal("0.95")), where, "effective_confidence"
        ),
        effective_from=effective_from,
        effective_to=effective_to,
        status=body.get("status", default_status),
        origin=body.get("origin", "manual"),
        created_by=str(body.get("created_by", "system")),
        created_at=created_at,
    )


_RULE_KEYS = frozenset(
    {
        "version",
        "name",
        "description",
        "priority",
        "effective_confidence",
        "status",
        "origin",
        "created_by",
    }
)


def _build_scope(raw: object, where: str) -> Scope:
    if not isinstance(raw, dict):
        raise RuleSourceError(f"{where}: 'scope' is required and must be a mapping")
    try:
        return Scope.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - re-raised with the file position attached
        raise RuleSourceError(f"{where}: invalid scope: {exc}") from exc


def _build_deductions(raw: object, where: str) -> tuple[Deduction, ...]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise RuleSourceError(f"{where}: 'deductions' must be a list")

    produced: list[str] = ["gross", "net"]
    built: list[Deduction] = []
    for position, item in enumerate(raw):
        try:
            deduction = Deduction.model_validate(item)
        except Exception as exc:  # noqa: BLE001 - re-raised with the file position attached
            raise RuleSourceError(f"{where}.deductions[{position}]: {exc}") from exc
        # A basis may name gross, net, or a deduction computed *earlier* in this
        # list. Naming a later one is not a chain, it is a cycle, and it must
        # fail at load rather than silently evaluate against zero.
        if deduction.basis not in produced:
            raise RuleSourceError(
                f"{where}.deductions[{position}]: basis {deduction.basis!r} is not gross, net, "
                f"or a deduction computed before it (available: {produced})"
            )
        if deduction.type in produced:
            raise RuleSourceError(
                f"{where}.deductions[{position}]: {deduction.type!r} is computed twice; "
                "the second would overwrite the basis the first published"
            )
        if deduction.rate < 0:
            raise RuleSourceError(f"{where}.deductions[{position}]: negative rate {deduction.rate}")
        if deduction.fixed_paise is not None and deduction.fixed_paise < 0:
            raise RuleSourceError(f"{where}.deductions[{position}]: negative fixed_paise")
        produced.append(deduction.type)
        built.append(deduction)
    return tuple(built)


def _build_tolerance(raw: object, where: str) -> Tolerance:
    if not isinstance(raw, dict):
        raise RuleSourceError(f"{where}: 'tolerance' is required and must be a mapping")
    try:
        tolerance = Tolerance.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - re-raised with the file position attached
        raise RuleSourceError(f"{where}: invalid tolerance: {exc}") from exc
    if tolerance.absolute_paise < 0 or tolerance.percent < 0:
        raise RuleSourceError(f"{where}: tolerance must be non-negative")
    return tolerance


def _reject_unbounded_stack(deductions: Sequence[Deduction], where: str) -> None:
    """Refuse a rule whose rates alone can deduct more than the gross.

    A rule that explains more money than existed is not a rule, it is a way to
    close anything. Fixed fees are excluded from the probe on purpose: a flat
    ₹20 collection fee legitimately exceeds a ₹5 settlement, and
    :mod:`fc.rules.apply` handles that case by declining to apply the rule
    rather than by pretending the arithmetic worked.
    """
    from fc.rules.evaluator import evaluate_deductions

    rate_only = tuple(d.model_copy(update={"fixed_paise": None}) for d in deductions)
    stack = evaluate_deductions(rate_only, _BOUND_PROBE_PAISE)
    if stack.total_paise > _BOUND_PROBE_PAISE:
        raise RuleSourceError(
            f"{where}: the deduction rates total more than 100% of gross "
            f"({stack.total_paise} of {_BOUND_PROBE_PAISE} paise at the probe amount)"
        )


def _reject_duplicate_versions(rules: Sequence[Rule], source: Path) -> None:
    seen: dict[tuple[str, int], int] = {}
    for index, rule in enumerate(rules):
        key = (rule.rule_id, rule.version)
        if key in seen:
            raise RuleSourceError(
                f"{source}: {rule.rule_id} version {rule.version} declared twice "
                f"(entries {seen[key]} and {index}); rules are immutable per version"
            )
        seen[key] = index


def _plain(value: object) -> object:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in sorted(value.items())}
    return value


def _decimal_text(value: Decimal) -> str:
    """``Decimal`` as plain text, so 18, 18.0 and 18.00 hash identically."""
    normalised = value.normalize()
    return format(normalised, "f")


def _as_int(value: object, where: str, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuleSourceError(f"{where}: {field} must be an integer, got {value!r}")
    return value


def _as_decimal(value: object, where: str, field: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value)
    raise RuleSourceError(f"{where}: {field} must be a number, got {value!r}")


def _as_date(value: object, where: str, field: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise RuleSourceError(f"{where}: {field} must be a date, got {value!r}")


def _as_optional_str(value: object) -> str | None:
    return None if value is None else str(value)
