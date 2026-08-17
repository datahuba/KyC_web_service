"""
F-CORREOS-REGISTRO (2026-08-17)
===============================

Kevin quiso "ver cuales son las que llegan a los usuarios" y "que lleguen a
todos los estudiantes y administrativos como docentes, todos los flujos",
pero decidio quedarse en el plan gratis de Brevo priorizando los correos con
las credenciales de los estudiantes.

Los numeros que fuerzan el diseño, medidos contra produccion el 2026-08-17:

  - 305 estudiantes + 28 de staff/docencia = 333 destinatarios, todos con
    email cargado.
  - Tope de Brevo (plan gratis): 300 correos/dia.
  - O sea que UN comunicado a todos los estudiantes (305) ya pasa el tope
    del dia sin haber mandado nada mas.

De ahi salen las dos reglas que fijan estos tests:

  1. Los correos con credenciales de acceso son CRITICOS y tienen cupo
     reservado. Sin ese correo el alumno no puede entrar al sistema; un
     recordatorio de pago que se atrasa un dia es solo una molestia.
  2. Lo que no entra en el cupo se ENCOLA, no se pierde. Antes el correo
     numero 301 desaparecia sin dejar rastro.
"""

import io
import os

import pytest


def _fuente(nombre_archivo):
    ruta = os.path.join(os.path.dirname(__file__), "..", nombre_archivo)
    return io.open(ruta, encoding="utf-8").read()


# ==========================================================================
# 1. El registro existe
# ==========================================================================

class TestRegistro:
    def test_hay_coleccion_de_correos(self):
        """
        Antes NO quedaba rastro de ningun correo: `send_email` devolvia un
        bool y los errores iban a print(). Nadie podia responder "¿le llego
        el correo al estudiante?".
        """
        from models.email_log import EmailLog
        campos = EmailLog.model_fields
        for c in ("destinatario", "asunto", "tipo", "prioridad", "estado",
                  "intentos", "error", "fecha_envio", "cuerpo_html"):
            assert c in campos, f"falta el campo {c}"
        assert EmailLog.Settings.name == "email_logs"

    def test_guarda_el_cuerpo_enviado(self):
        """
        Hace falta para dos cosas: reintentar sin re-generar el HTML, y que
        el staff pueda ver exactamente que se envio cuando alguien reclama.
        """
        from models.email_log import EmailLog
        assert "cuerpo_html" in EmailLog.model_fields

    def test_se_puede_rastrear_por_persona(self):
        """Para responder "este alumno dice que no le llego nada"."""
        from models.email_log import EmailLog
        assert "destinatario_id" in EmailLog.model_fields
        assert "destinatario_nombre" in EmailLog.model_fields

    def test_el_modelo_esta_registrado_en_beanie(self):
        """Si falta, todo tira 500 en runtime."""
        src = _fuente("core/database.py")
        assert "EmailLog" in src

    def test_el_router_esta_registrado(self):
        src = _fuente("api/api.py")
        assert "email_logs" in src
        assert '"/email-logs"' in src


# ==========================================================================
# 2. Prioridad: las credenciales primero
# ==========================================================================

class TestPrioridad:
    def test_las_credenciales_de_preinscripcion_son_criticas(self):
        """
        Es EL correo que Kevin pidio blindar: lleva usuario y contraseña
        inicial, asi que sin el, el alumno no puede entrar.
        """
        from models.email_log import PrioridadEmail
        from services.email_service import PRIORIDAD_POR_TIPO, TipoEmail
        assert PRIORIDAD_POR_TIPO[TipoEmail.CREDENCIALES_PREINSCRIPCION] == PrioridadEmail.CRITICA

    def test_el_reset_de_password_tambien_es_critico(self):
        """Mismo motivo: sin ese correo el usuario queda afuera."""
        from models.email_log import PrioridadEmail
        from services.email_service import PRIORIDAD_POR_TIPO, TipoEmail
        assert PRIORIDAD_POR_TIPO[TipoEmail.RESET_PASSWORD] == PrioridadEmail.CRITICA

    def test_los_comunicados_masivos_son_los_primeros_en_diferirse(self):
        """
        Son los que consumen cientos de correos de golpe (305 estudiantes).
        Si tuvieran prioridad alta, un comunicado dejaria sin cupo a las
        credenciales del resto del dia.
        """
        from models.email_log import PrioridadEmail
        from services.email_service import PRIORIDAD_POR_TIPO, TipoEmail
        assert PRIORIDAD_POR_TIPO[TipoEmail.COMUNICADO] == PrioridadEmail.NORMAL
        assert PRIORIDAD_POR_TIPO[TipoEmail.RECORDATORIO_PAGO] == PrioridadEmail.NORMAL

    def test_todo_tipo_tiene_prioridad_asignada(self):
        """Un tipo sin prioridad caeria en el default silenciosamente."""
        from services.email_service import PRIORIDAD_POR_TIPO, TipoEmail
        tipos = [v for k, v in vars(TipoEmail).items() if not k.startswith("_")]
        for t in tipos:
            assert t in PRIORIDAD_POR_TIPO, f"el tipo '{t}' no tiene prioridad"


# ==========================================================================
# 3. Cupo diario
# ==========================================================================

class TestCupo:
    def test_la_cuota_default_es_el_tope_de_brevo(self):
        from core.config import settings
        assert settings.EMAIL_CUOTA_DIARIA == 300

    def test_hay_cupo_reservado_para_los_criticos(self):
        """
        El colchon que los correos NO criticos no pueden tocar. Sin esto, un
        comunicado de la mañana (305 correos) dejaria sin credenciales a un
        alumno que se preinscribe a la tarde.
        """
        from core.config import settings
        assert settings.EMAIL_CUPO_RESERVADO_CRITICOS > 0
        assert settings.EMAIL_CUPO_RESERVADO_CRITICOS < settings.EMAIL_CUOTA_DIARIA

    def test_los_criticos_ven_mas_cupo_que_el_resto(self):
        """
        Es la regla central: con el mismo consumo del dia, un critico tiene
        mas margen que un comunicado.
        """
        src = _fuente("services/email_service.py")
        assert "if prioridad == PrioridadEmail.CRITICA:" in src
        assert "settings.EMAIL_CUPO_RESERVADO_CRITICOS" in src

    def test_el_dia_se_corta_en_hora_de_bolivia(self):
        """
        Si se contara por dia UTC, el cupo se reiniciaria a las 20:00 hora
        local, en pleno horario de uso de la unidad.
        """
        src = _fuente("services/email_service.py")
        assert "def _inicio_del_dia_utc" in src
        assert "timedelta(hours=4)" in src


# ==========================================================================
# 4. Nada se pierde
# ==========================================================================

class TestNadaSePierde:
    def test_sin_cupo_se_encola_en_vez_de_perderse(self):
        from models.email_log import EstadoEmail
        src = _fuente("services/email_service.py")
        assert "EstadoEmail.ENCOLADO" in src
        assert EstadoEmail.ENCOLADO in EstadoEmail.TODOS

    def test_quedarse_sin_cupo_no_cuenta_como_intento_fallido(self):
        """
        Si contara, el correo se acercaria al descarte por una razon que no
        es suya y terminaria tirandose sin haberse intentado nunca.
        """
        src = _fuente("services/email_service.py")
        i_cupo = src.index("if await cupo_disponible(log.prioridad) <= 0:")
        i_intento = src.index("log.intentos += 1")
        assert i_cupo < i_intento, "el contador de intentos se toca antes de chequear el cupo"

    def test_hay_tope_de_reintentos(self):
        """Reintentar para siempre un email mal escrito solo gasta cupo."""
        from services.email_service import MAX_INTENTOS
        assert 1 < MAX_INTENTOS <= 10

    def test_la_cola_se_procesa_por_prioridad(self):
        """Un lote de comunicados no debe postergar una credencial."""
        src = _fuente("services/email_service.py")
        assert "orden_prioridad" in src
        assert "async def procesar_pendientes" in src

    def test_un_fallo_de_smtp_no_rompe_el_flujo_de_negocio(self):
        """
        Que no salga un correo no puede hacer fallar el aprobar un pago o el
        inscribir a alguien.
        """
        src = _fuente("services/email_service.py")
        assert "except Exception" in src
        assert "SIEMPRE devuelve el EmailLog" in src


# ==========================================================================
# 5. Todos los flujos pasan por el servicio
# ==========================================================================

class TestCobertura:
    def test_ningun_flujo_manda_correo_por_afuera(self):
        """
        Si algun modulo sigue llamando a `send_email` directo, ese correo no
        queda registrado ni respeta el cupo — que es exactamente el problema
        que este cambio vino a resolver.
        """
        import glob

        raiz = os.path.join(os.path.dirname(__file__), "..")
        sospechosos = []
        for patron in ("api/*.py", "services/*.py"):
            for ruta in glob.glob(os.path.join(raiz, patron)):
                base = os.path.basename(ruta)
                # email_service ES el que tiene derecho a llamar a SMTP.
                if base == "email_service.py":
                    continue
                txt = io.open(ruta, encoding="utf-8").read()
                if "await send_email(" in txt:
                    sospechosos.append(base)
        assert not sospechosos, (
            "estos modulos siguen mandando correo sin registrar: %s" % sospechosos
        )

    def test_el_flujo_de_credenciales_usa_el_tipo_correcto(self):
        src = _fuente("services/pre_registration_service.py")
        assert "TipoEmail.CREDENCIALES_PREINSCRIPCION" in src


# ==========================================================================
# 5b. El job que vacia la cola
# ==========================================================================

class TestJob:
    def test_main_importa_sin_romperse(self):
        """
        La suite no importaba `main.py`, asi que un error de sintaxis o una
        funcion faltante ahi pasaba desapercibido hasta el arranque en
        produccion. Paso exactamente eso al agregar este job: la llamada
        quedo en el startup pero la definicion se habia borrado, y los 777
        tests seguian en verde.
        """
        import main
        assert main.app is not None

    def test_el_job_de_la_cola_existe_y_esta_enganchado(self):
        """
        Sin este job, lo que se encola por falta de cupo no sale nunca: se
        quedaria esperando para siempre.
        """
        import inspect
        import main

        assert inspect.iscoroutinefunction(main._job_procesar_cola_correos)
        assert main._INTERVALO_JOB_CORREOS_SEGUNDOS > 0
        # Y que el startup realmente lo lance.
        src = _fuente("main.py")
        assert "asyncio.create_task(_job_procesar_cola_correos())" in src

    def test_el_job_no_corre_apenas_arranca(self):
        """
        Con `uvicorn --reload` el startup se dispara en CADA guardado de
        archivo. Si la primera corrida fuera inmediata, cada Ctrl+S mandaria
        correos reales contra la base compartida con produccion. Por eso el
        sleep va ANTES del trabajo, igual que en el job de congelado.
        """
        src = _fuente("main.py")
        cuerpo = src[src.index("async def _job_procesar_cola_correos"):]
        cuerpo = cuerpo[: cuerpo.index("@app.on_event")]
        i_sleep = cuerpo.index("await asyncio.sleep")
        i_trabajo = cuerpo.index("procesar_pendientes")
        assert i_sleep < i_trabajo, "el job procesa antes de esperar el intervalo"


# ==========================================================================
# 6. El panel
# ==========================================================================

class TestPanel:
    def test_el_registro_es_solo_para_admin_y_superadmin(self):
        """
        Guarda el CUERPO de los correos, y el de credenciales trae la
        contraseña inicial del alumno en texto plano. No se abre al resto
        del staff.
        """
        src = _fuente("api/email_logs.py")
        assert "def _puede_ver" in src
        assert "UserRole.ADMIN" in src and "UserRole.SUPERADMIN" in src

    def test_el_listado_no_manda_el_html_de_cada_correo(self):
        """Serian cientos de KB por pagina que nadie mira."""
        src = _fuente("api/email_logs.py")
        assert "incluir_cuerpo" in src

    def test_la_busqueda_por_email_escapa_el_regex(self):
        """
        Un punto sin escapar en 'a.b@x.com' funcionaria como comodin y
        traeria correos de otras personas.
        """
        src = _fuente("api/email_logs.py")
        assert "_re.escape(destinatario)" in src


# ==========================================================================
# 7. Tipos de notificacion (F-NOTIF-TIPOS)
# ==========================================================================

class TestTiposDeNotificacion:
    def test_hay_catalogo_de_eventos(self):
        """
        Antes `tipo_alerta` guardaba solo la SEVERIDAD visual
        (info/success/warning/error). Medido en produccion: 849
        notificaciones con apenas esos 4 valores. Sin saber QUE paso no se
        puede filtrar, agrupar ni dar preferencias por tipo.
        """
        from models.notification_events import EventoNotificacion
        eventos = EventoNotificacion.todos()
        assert len(eventos) > 25, "el catalogo quedo demasiado corto"
        # Sale de los titulos que el codigo ya usaba, no es inventado.
        for esperado in ("pago_aprobado", "nota_validada", "alerta_mora",
                         "documento_rechazado", "inscripcion_aprobada"):
            assert esperado in eventos

    def test_el_campo_es_opcional(self):
        """
        Las 849 notificaciones historicas no lo tienen y no se van a
        reescribir. Si fuera obligatorio, leerlas reventaria.
        """
        from models.notification import Notification
        campo = Notification.model_fields["evento"]
        assert campo.default is None
        assert not campo.is_required()

    def test_el_servicio_acepta_el_evento(self):
        import inspect
        from services.notification_service import create_notification
        assert "evento" in inspect.signature(create_notification).parameters

    def test_cada_evento_tiene_grupo_para_la_ui(self):
        """Sin agrupar, la UI mostraria una lista plana de 33 eventos."""
        from models.notification_events import GRUPO_POR_EVENTO, EventoNotificacion
        for e in EventoNotificacion.todos():
            assert e in GRUPO_POR_EVENTO, f"el evento '{e}' no tiene grupo"


# ==========================================================================
# 8. El estudiante se entera de la mora (F-NOTIF-ESTUDIANTE)
# ==========================================================================

class TestMoraAlEstudiante:
    def test_la_alerta_de_mora_tambien_le_llega_al_estudiante(self):
        """
        Antes la alerta preventiva iba SOLO al encargado. O sea que el unico
        que no sabia que estaba por caer en abandono automatico era
        justamente el que podia evitarlo pagando.

        Es la brecha mas clara que aparecio al revisar los 33 puntos donde se
        notifica: el resto de los eventos que le importan al estudiante
        (pagos, notas, documentos, inscripciones) ya lo incluian.
        """
        src = _fuente("services/congelado_service.py")
        bloque = src[src.index("async def _notificar_mora_preventiva"):]
        bloque = bloque[: bloque.index("async def _marcar_abandono_automatico")]
        assert 'tipo_destinatario="user"' in bloque, "se perdio la notificacion al encargado"
        assert 'tipo_destinatario="student"' in bloque, "el estudiante no se entera de la mora"
        # Y que lo lleve a donde puede resolverlo, no a una pantalla de lectura.
        assert '"/app/payments"' in bloque
