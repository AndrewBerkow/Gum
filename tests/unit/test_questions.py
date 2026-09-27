from langchain_typesafe import Choice, Noul

from app.jev import QUESTIONS


def test_ids_types_labels():
    assert set(QUESTIONS) == {"unsafe", "scope", "complexity"}
    assert isinstance(QUESTIONS["unsafe"], Noul) and QUESTIONS["unsafe"].criteria is not None
    assert isinstance(QUESTIONS["scope"], Choice) and isinstance(QUESTIONS["complexity"], Choice)
    assert set(QUESTIONS["scope"].criteria) == {"valid_request", "noise", "out_of_scope"}
    assert set(QUESTIONS["complexity"].criteria) == {"simple", "complex"}
