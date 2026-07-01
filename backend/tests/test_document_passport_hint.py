from app.services.document_passport_hint import infer_doc_type_hint_from_filename


def test_hint_from_objection_filename():
    assert infer_doc_type_hint_from_filename("00. возражения ШАК.pdf") == "возражение"


def test_hint_from_contract_filename():
    assert infer_doc_type_hint_from_filename("договор поставки.pdf") == "договор"


def test_hint_defaults_to_other():
    assert infer_doc_type_hint_from_filename("funds_movement.pdf") == "прочее"
