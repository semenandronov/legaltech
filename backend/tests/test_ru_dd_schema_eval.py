"""CI: RU DD schema eval packs (lease/supply/services) — rules only, no LLM."""

from app.services.ru_dd_schema_eval import run_all_packs, run_pack


def test_ru_lease_schema_seed_accuracy():
    summary = run_pack("lease")
    assert summary["scored"] >= 4
    assert summary["accuracy"] >= 0.75, summary
    assert summary["schema_hit_rate"] >= 0.75, summary


def test_ru_supply_schema_seed_accuracy():
    summary = run_pack("supply")
    assert summary["scored"] >= 4
    assert summary["accuracy"] >= 0.75, summary


def test_ru_services_schema_seed_accuracy():
    summary = run_pack("services")
    assert summary["scored"] >= 4
    assert summary["accuracy"] >= 0.75, summary


def test_ru_dd_all_packs_aggregate():
    overall = run_all_packs()
    assert overall["scored"] >= 12
    assert overall["accuracy"] >= 0.75, overall["by_pack"]
