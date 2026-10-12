from domain.i18n import detect_language
from tools import search_medication


def test_detects_spanish():
    assert detect_language("Tengo fiebre y dolor") == "es"


def test_detects_english():
    assert detect_language("I have a headache") == "en"


def test_searches_a_local_medication():
    answer = search_medication.invoke({
        "name": "ibuprofeno",
        "language": "es",
    })
    assert "ibuprofeno" in answer.lower()
