from domain.i18n import detect_language
from tools import buscar_medicamento


def test_detecta_espanol():
    assert detect_language("Tengo fiebre y dolor") == "es"


def test_detecta_ingles():
    assert detect_language("I have a headache") == "en"


def test_busca_un_medicamento_local():
    respuesta = buscar_medicamento.invoke({
        "nombre": "ibuprofeno",
        "language": "es",
    })
    assert "ibuprofeno" in respuesta.lower()