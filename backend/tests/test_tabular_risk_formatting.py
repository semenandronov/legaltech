"""Risk cell formatting must never emit empty «- Риск» placeholders."""

from app.services.tabular_risk_analysis_graph import RiskItem, _format_risks_fallback


def test_format_risks_uses_quote_when_title_is_placeholder():
    items = [
        RiskItem(
            title="Риск",
            detail="",
            severity="high",
            quote="7.7. Риск гибели и повреждения Имущества лежит на Арендаторе.",
        ),
        RiskItem(
            title="Штраф за порчу имущества",
            detail="Арендатор платит штраф в размере стоимости имущества.",
            severity="medium",
            quote="7.9. За нарушение...",
        ),
    ]
    text = _format_risks_fallback(items)
    assert "Риск гибели и повреждения" in text
    assert "Штраф за порчу имущества" in text
    assert text.count("- [") == 2
    assert "- [high] Риск\n" not in text
    assert not text.startswith("- Риск\n- Риск")
