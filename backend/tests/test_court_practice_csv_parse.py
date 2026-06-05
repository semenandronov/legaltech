"""CSV ingest for court practice (headerless export)."""
from app.services.court_practice_service import _parse_csv_rows, _pick_column, _TEXT_COLUMNS


def test_headerless_csv_without_header_row():
    content = (
        "А40-12345/2020,Определение,30.06.2020,Верховный Суд РФ,doc-1,"
        "установил: мотивировочная часть судебного акта.\n"
    ).encode("utf-8")
    rows = _parse_csv_rows(content)
    assert len(rows) == 1
    assert rows[0]["номер дела"] == "А40-12345/2020"
    text = _pick_column(rows[0], _TEXT_COLUMNS)
    assert "мотивировочная" in text
