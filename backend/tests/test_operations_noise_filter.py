"""Tests for operational noise heuristics."""

from app.services.operations_noise_filter import (
    is_operational_noise_row,
    is_operational_noise_text,
)


def test_operational_noise_detects_tax_payment():
    assert is_operational_noise_text("Уплата НДФЛ за январь 2024")


def test_operational_noise_detects_rent():
    assert is_operational_noise_text("Оплата аренды офиса по договору №12")


def test_operational_noise_ignores_counterparty_transfer():
    assert not is_operational_noise_text('Перевод ООО "Вектор" по договору займа')


def test_operational_noise_row_uses_columns():
    assert is_operational_noise_row(
        description="Платёж",
        row_columns={"Назначение": "Страховые взносы в СФР"},
    )
