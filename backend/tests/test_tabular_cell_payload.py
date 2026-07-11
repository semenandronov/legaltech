from types import SimpleNamespace

from langchain_core.documents import Document

from app.services.tabular_cell_payload import build_tabular_cell_db_payload
from app.services.tabular_review_models import TabularCellExtractionModel


def _file(text: str = "Договор поставки между ООО Альфа и ООО Бета") -> SimpleNamespace:
    return SimpleNamespace(id="file-1", original_text=text)


def _column() -> SimpleNamespace:
    return SimpleNamespace(id="col-1", column_type="text")


def test_build_tabular_cell_db_payload_enriches_model_refs_with_primary_provenance():
    result = TabularCellExtractionModel(
        cell_value="ООО Альфа",
        verbatim_extract="Договор поставки между ООО Альфа",
        reasoning="Найдено в шапке",
        confidence=0.95,
        column_type="text",
        source_references=[
            {"text": "Договор поставки между ООО Альфа"},
            {"text": "ООО Бета", "page": 3},
        ],
    )

    docs = [
        Document(
            page_content="Договор поставки между ООО Альфа",
            metadata={
                "source_page": 2,
                "char_start": 5,
                "char_end": 40,
                "bbox_regions": [{"x0": 10, "y0": 20, "x1": 30, "y1": 40}],
                "page_bbox": {"width": 600, "height": 800},
            },
        )
    ]

    payload = build_tabular_cell_db_payload(
        file=_file(),
        column=_column(),
        result=result,
        included_docs=docs,
        db=None,
        verification_outcome=None,
    )

    refs = payload["source_references"]
    assert len(refs) == 2

    primary = refs[0]
    assert primary["text"] == "Договор поставки между ООО Альфа"
    assert primary["page"] == 2
    assert primary["doc_id"] == "file-1"
    assert primary["char_start"] is not None
    assert primary["char_end"] is not None
    assert primary["bbox"] == {"x0": 10.0, "y0": 20.0, "x1": 30.0, "y1": 40.0}
    assert primary["page_bbox"] == {"width": 600.0, "height": 800.0}

    secondary = refs[1]
    assert secondary["text"] == "ООО Бета"
    assert secondary["page"] == 3
    assert secondary["doc_id"] == "file-1"
    assert "bbox" not in secondary
