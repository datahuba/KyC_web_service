"""
Tests para el servicio de tickets de un solo uso del stream SSE
=================================================================

FIX-SSE-TOKEN-URL (2026-08-17): antes el JWT completo viajaba en la query
string de /notifications/stream, quedando expuesto en el historial del
navegador, en los access logs de Nginx y en el header Referer. Este
servicio emite tickets cortos, de un solo uso y de corta duración para
reemplazar eso.

F-FIX-SSE-TICKET-MULTIWORKER (2026-08-19): la primera version guardaba
los tickets en un dict en memoria del proceso — roto en produccion, que
corre `uvicorn --workers 4` (4 procesos sin memoria compartida): un
ticket emitido por un worker no existia en el dict de otro, causando 401
en ~75% de los intentos. Se migro a MongoDB (compartido por los 4
workers). Este proyecto NO tiene harness de MongoDB para tests (ver
`AGENTS.md`/memoria del proyecto), asi que estos tests son de inspeccion
de fuente en vez de ejercitar `issue()`/`consume()` contra una DB real —
mismo patron que el resto de la suite para este tipo de casos.
"""
import io
import os


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class TestSSETicketServiceUsaMongoNoMemoria:
    def test_no_queda_ningun_dict_en_memoria_para_tickets(self):
        src = _fuente("services", "sse_ticket_service.py")
        assert "_tickets" not in src
        assert "Dict[str, Tuple" not in src

    def test_issue_inserta_en_mongo(self):
        src = _fuente("services", "sse_ticket_service.py")
        ini = src.index("async def issue")
        fin = src.index("async def consume")
        cuerpo = src[ini:fin]
        assert "SSETicket(" in cuerpo
        assert ".insert()" in cuerpo

    def test_consume_usa_find_one_and_delete_atomico(self):
        """
        find_one_and_delete es atomico a nivel de MongoDB — necesario para
        que el ticket siga siendo de un solo uso aunque dos requests
        concurrentes caigan en workers distintos.
        """
        src = _fuente("services", "sse_ticket_service.py")
        ini = src.index("async def consume")
        cuerpo = src[ini:]
        assert "find_one_and_delete" in cuerpo
        assert "get_motor_collection()" in cuerpo

    def test_consume_valida_expiracion_explicitamente(self):
        """
        El indice TTL de Mongo es solo limpieza de respaldo (corre cada
        ~60s, no instantaneo) — la validez real la decide `consume()`.
        """
        src = _fuente("services", "sse_ticket_service.py")
        ini = src.index("async def consume")
        cuerpo = src[ini:]
        assert "_TICKET_TTL_SECONDS" in cuerpo
        assert "timedelta" in cuerpo


class TestSSETicketModel:
    def test_modelo_registrado_como_document_de_beanie(self):
        src = _fuente("models", "sse_ticket.py")
        assert "class SSETicket(Document)" in src

    def test_indice_unico_sobre_ticket(self):
        src = _fuente("models", "sse_ticket.py")
        assert 'unique=True' in src
        assert '"ticket"' in src

    def test_indice_ttl_de_respaldo(self):
        src = _fuente("models", "sse_ticket.py")
        assert "expireAfterSeconds=60" in src

    def test_registrado_en_document_models_de_database_py(self):
        src = _fuente("core", "database.py")
        assert "SSETicket" in src
        ini = src.index("document_models=[")
        fin = src.index("]", ini)
        assert "SSETicket" in src[ini:fin]
