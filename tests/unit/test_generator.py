from __future__ import annotations

import json

from fc.generator import seed
from fc.generator.scenarios import EPOCH_MS, INGESTED_AT, OPENING_BALANCE_PAISE, TENANT_ID
from fc.ingest.bank_csv import parse_bank_csv
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.ingest.razorpay import parse_razorpay_recon
from fc.ingest.tally import parse_tally_csv
from fc.models.ids import deterministic_factory


def _issue_id():
    return deterministic_factory(seed=7, epoch_ms=EPOCH_MS)


def test_same_seed_and_n_produce_byte_identical_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(seed, "OUTPUT_DIR", tmp_path)
    seed.generate(7, 80)
    first = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    seed.generate(7, 80)
    second = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert first == second


def test_generated_files_parse_cleanly_through_the_real_adapters(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(seed, "OUTPUT_DIR", tmp_path)
    manifest = seed.generate(11, 80)
    assert manifest["expected_counts_consistent"] is True

    rp_rows = json.loads((tmp_path / "razorpay_recon.json").read_text(encoding="utf-8"))
    rp_result = parse_razorpay_recon(
        rp_rows,
        run_id="run_test",
        tenant_id=TENANT_ID,
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert rp_result.rejections == ()

    bank_text = (tmp_path / "bank_statement.csv").read_text(encoding="utf-8")
    bank_result = parse_bank_csv(
        bank_text,
        run_id="run_test",
        tenant_id=TENANT_ID,
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=OPENING_BALANCE_PAISE,
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert bank_result.ingest.rejections == ()
    assert bank_result.balanced is True

    tally_text = (tmp_path / "tally_daybook.csv").read_text(encoding="utf-8")
    tally_result = parse_tally_csv(
        tally_text,
        run_id="run_test",
        tenant_id=TENANT_ID,
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert tally_result.rejections == ()


def test_every_scenario_appears_at_least_twice_at_n_500(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(seed, "OUTPUT_DIR", tmp_path)
    seed.generate(42, 500)
    gt_text = (tmp_path / "ground_truth.jsonl").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in gt_text.splitlines()]
    groups_by_scenario: dict[int, set[str]] = {}
    for entry in entries:
        if entry["scenario"] is not None:
            groups_by_scenario.setdefault(entry["scenario"], set()).add(entry["gt_match_group"])
    for scenario_id in range(1, 19):  # 16 original + 17/18 marketplace additions
        n_groups = len(groups_by_scenario.get(scenario_id, set()))
        assert n_groups >= 2, f"scenario {scenario_id} underrepresented"


def test_scenario_3_batch_sizes_include_one_past_the_subset_sum_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(seed, "OUTPUT_DIR", tmp_path)
    seed.generate(42, 500)
    rp_rows = json.loads((tmp_path / "razorpay_recon.json").read_text(encoding="utf-8"))
    gt_text = (tmp_path / "ground_truth.jsonl").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in gt_text.splitlines()]
    scenario3_keys = {e["key"] for e in entries if e["scenario"] == 3}
    payment_counts: dict[str, int] = {}
    for row in rp_rows:
        if row["entity_id"] in scenario3_keys and row["type"] == "payment":
            payment_counts[row["settlement_id"]] = payment_counts.get(row["settlement_id"], 0) + 1
    assert sorted(payment_counts.values()) == [14, 25, 41]


def test_marketplace_rate_mismatch_and_midperiod_change_are_present(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(seed, "OUTPUT_DIR", tmp_path)
    seed.generate(42, 500)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["by_scenario"]["17"] > 0
    assert manifest["by_scenario"]["18"] > 0
    assert "amount_variance" in manifest["by_category"]


def test_bank_narration_comma_overflow_is_present_and_parses(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(seed, "OUTPUT_DIR", tmp_path)
    seed.generate(42, 500)
    bank_text = (tmp_path / "bank_statement.csv").read_text(encoding="utf-8")
    overflow_lines = [ln for ln in bank_text.splitlines()[1:] if ln.count(",") > 6]
    assert overflow_lines, "expected at least one narration with an embedded comma"
    bank_result = parse_bank_csv(
        bank_text,
        run_id="run_test",
        tenant_id=TENANT_ID,
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=OPENING_BALANCE_PAISE,
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert bank_result.ingest.rejections == ()


def test_truncation_scenario_includes_a_genuinely_midcut_reference(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(seed, "OUTPUT_DIR", tmp_path)
    seed.generate(42, 500)
    bank_text = (tmp_path / "bank_statement.csv").read_text(encoding="utf-8")
    parser = HdfcNarrationParser()
    midcut_found = False
    for line in bank_text.splitlines()[1:]:
        narration = line.split(",")[2]
        if not narration.startswith("UPI-"):
            continue
        parsed = parser.parse(narration)
        assert parsed.rail == "upi"
        assert parsed.truncated
        assert parsed.reference is not None and len(parsed.reference) < 12
        midcut_found = True
    assert midcut_found


def test_manifest_bucket_counts_sum_to_total_ground_truth_rows(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(seed, "OUTPUT_DIR", tmp_path)
    manifest = seed.generate(3, 120)
    total = sum(manifest["by_bucket"].values())
    assert total == manifest["total_ground_truth_rows"]


def test_truncated_narration_scenario_is_genuinely_short(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(seed, "OUTPUT_DIR", tmp_path)
    seed.generate(42, 500)
    bank_text = (tmp_path / "bank_statement.csv").read_text(encoding="utf-8")
    parser = HdfcNarrationParser()
    found_truncated = False
    for line in bank_text.splitlines()[1:]:
        narration = line.split(",")[2]
        parsed = parser.parse(narration)
        if parsed.truncated:
            found_truncated = True
            assert len(narration) >= 98
    assert found_truncated
