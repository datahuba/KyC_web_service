# -*- coding: utf-8 -*-
"""Tests para F-075: Lista de Postgraduantes Habilitados.

Cubre:
- Estructura del response (encabezado + rows + totales)
- Lista por módulo específico
- Lista de matrícula
- Lista de todos los módulos
- Exclusión de estudiantes SIN pago aprobado
- Suma de pagos parciales en un solo registro por estudiante-módulo
- Inclusión de beca/descuento
- Periodo (rango de fechas) en encabezado
- Total coherente
- F-075-FIX-8: 3 estados (PAGADO/PARCIAL/PENDIENTE) + orden 2 grupos
- F-076: refactor N+1 -> batch loading (mocks actualizados)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from bson import ObjectId

# Importación del service
from services import payment_service


def _make_payment(estado="aprobado", cantidad=294.0, concepto="Módulo 1", fecha=None, trans="12345", inscripcion_id=None):
    p = MagicMock()
    p.estado_pago = estado
    p.cantidad_pago = cantidad
    p.concepto = concepto
    p.numero_transaccion = trans
    p.fecha_comprobante = fecha or datetime(2026, 7, 1)
    p.fecha_subida = fecha or datetime(2026, 7, 1)
    p.inscripcion_id = inscripcion_id or ObjectId()
    p.estudiante_id = ObjectId()
    return p


def _make_enrollment(est_id, curso_id, modulos_pagados=(294.0, 0, 0, 0, 0), descuento_curso=0.0, descuento_personal=0.0, beca_id=None):
    """Crea un mock enrollment con módulos y descuentos."""
    e = MagicMock()
    e.id = ObjectId()
    e.estudiante_id = est_id
    e.curso_id = curso_id
    e.estado = "activo"
    e.costo_matricula = 300.0
    e.descuento_curso_id = None
    e.descuento_curso_aplicado = descuento_curso
    e.descuento_estudiante_id = beca_id
    e.descuento_personalizado = descuento_personal
    # modulos: 5 módulos
    modulos = []
    for i, pago in enumerate(modulos_pagados, 1):
        m = MagicMock()
        m.nombre = f"Módulo {i}"
        m.costo = 588.0
        m.monto_pagado = pago
        m.estado = "Pagado" if pago >= 588 else ("Parcial" if pago > 0 else "Pendiente")
        modulos.append(m)
    e.modulos = modulos
    return e


def _make_student(est_id, nombre="Juan Pérez", carnet="1234567", complemento=None):
    s = MagicMock()
    s.id = est_id
    s.nombre = nombre
    s.carnet = carnet
    s.complemento_carnet = complemento
    s.registro = "REG-001"
    return s


def _make_course(curso_id, n_modulos=5, tipo="diplomado", nombre="DIPL-IA-2026"):
    c = MagicMock()
    c.id = curso_id
    c.codigo = "DIPL-IA-2026"
    c.nombre_programa = nombre
    c.tipo_curso = MagicMock()
    c.tipo_curso.value = tipo
    c.matricula_interno = 300.0
    c.costo_total_interno = 2940.0
    # Módulos
    modulos = []
    for i in range(n_modulos):
        m = MagicMock()
        m.nombre = f"Fundamentos Módulo {i+1}"
        m.costo = 588.0
        m.docente_id = None
        modulos.append(m)
    c.modulos = modulos
    return c


# Helper para configurar mocks con la nueva estructura batch loading
def _setup_mocks(MockCourse, MockEnrollment, MockStudent, MockPayment, MockDiscount, MockUser,
                 curso, enrollments, students, pagos, descuentos=None, docentes=None):
    """Configura mocks para F-075-FIX-8 batch loading (F-076)."""
    MockCourse.get = AsyncMock(return_value=curso)
    MockEnrollment.find = MagicMock()
    MockEnrollment.find.return_value.to_list = AsyncMock(return_value=enrollments)
    # Student: una sola query con In() -> to_list()
    MockStudent.find = MagicMock()
    MockStudent.find.return_value.to_list = AsyncMock(return_value=students)
    # Payment: una sola query con In() y sort() -> to_list()
    MockPayment.find = MagicMock()
    MockPayment.find.return_value.sort = MagicMock()
    MockPayment.find.return_value.sort.return_value.to_list = AsyncMock(return_value=pagos)
    # Discount: una sola query con In() -> to_list()
    if descuentos:
        MockDiscount.find = MagicMock()
        MockDiscount.find.return_value.to_list = AsyncMock(return_value=descuentos)
    # User: una sola query con In() -> to_list() (docentes)
    if docentes:
        MockUser.find = MagicMock()
        MockUser.find.return_value.to_list = AsyncMock(return_value=docentes)


@pytest.mark.asyncio
async def test_generar_lista_habilitados_estructura_response():
    """Verifica que la respuesta tiene la estructura esperada."""
    curso_id = ObjectId()
    est_id = ObjectId()
    curso = _make_course(curso_id, n_modulos=5)
    enrollment = _make_enrollment(est_id, curso_id, modulos_pagados=(294.0, 0, 0, 0, 0))
    student = _make_student(est_id, nombre="Test User")
    pago = _make_payment(cantidad=294.0, fecha=datetime(2026, 7, 15), trans="ABC123", inscripcion_id=enrollment.id)

    with patch.object(payment_service, 'Course') as MockCourse, \
         patch.object(payment_service, 'Enrollment') as MockEnrollment, \
         patch.object(payment_service, 'Student') as MockStudent, \
         patch.object(payment_service, 'Payment') as MockPayment, \
         patch.object(payment_service, 'Discount') as MockDiscount, \
         patch.object(payment_service, 'In', lambda *args: MagicMock()), \
         patch('models.user.User') as MockUser:

        _setup_mocks(MockCourse, MockEnrollment, MockStudent, MockPayment, MockDiscount, MockUser,
                     curso, [enrollment], [student], [pago])

        result = await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=1)

    assert "curso" in result
    assert "encabezado" in result
    assert "rows" in result
    assert "total_importe" in result
    assert "total_estudiantes" in result
    assert result["encabezado"]["titulo"] == "LISTA DE POSTGRADUANTES HABILITADOS"
    assert result["curso"]["codigo"] == "DIPL-IA-2026"
    assert result["total_estudiantes"] == 1
    assert result["total_importe"] == 294.0
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["nombre"] == "TEST USER"  # MAYÚSCULAS
    assert row["importe"] == 294.0
    assert row["modulo_index"] == 1


@pytest.mark.asyncio
async def test_generar_lista_habilitados_incluye_todos():
    """F-075-FIX-8: TODOS los estudiantes aparecen, pagados Y no pagados."""
    curso_id = ObjectId()
    est1_id = ObjectId()  # este pagó
    est2_id = ObjectId()  # este NO pagó
    curso = _make_course(curso_id)
    enr1 = _make_enrollment(est1_id, curso_id, modulos_pagados=(588.0, 0, 0, 0, 0))
    enr2 = _make_enrollment(est2_id, curso_id, modulos_pagados=(0, 0, 0, 0, 0))  # sin pago
    s1 = _make_student(est1_id, nombre="PAGÓ")
    s2 = _make_student(est2_id, nombre="NO PAGÓ")
    pago1 = _make_payment(cantidad=588.0, fecha=datetime(2026, 7, 10), inscripcion_id=enr1.id)

    with patch.object(payment_service, 'Course') as MockCourse, \
         patch.object(payment_service, 'Enrollment') as MockEnrollment, \
         patch.object(payment_service, 'Student') as MockStudent, \
         patch.object(payment_service, 'Payment') as MockPayment, \
         patch.object(payment_service, 'Discount') as MockDiscount, \
         patch.object(payment_service, 'In', lambda *args: MagicMock()), \
         patch('models.user.User') as MockUser:

        _setup_mocks(MockCourse, MockEnrollment, MockStudent, MockPayment, MockDiscount, MockUser,
                     curso, [enr1, enr2], [s1, s2], [pago1])

        result = await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=1)

    # Ambos estudiantes deben aparecer
    assert result["total_estudiantes"] == 2
    nombres = [r["nombre"] for r in result["rows"]]
    assert "PAGÓ" in nombres
    assert "NO PAGÓ" in nombres

    # El pagador debe tener estado PAGADO e importe > 0
    row_pagado = next(r for r in result["rows"] if r["nombre"] == "PAGÓ")
    assert row_pagado["estado_pago"] == "PAGADO"
    assert row_pagado["importe"] == 588.0
    assert row_pagado["monto_pendiente"] == 0.0

    # El no-pagador debe tener estado PENDIENTE, importe=0 y monto_pendiente=costo
    row_pendiente = next(r for r in result["rows"] if r["nombre"] == "NO PAGÓ")
    assert row_pendiente["estado_pago"] == "PENDIENTE"
    assert row_pendiente["importe"] == 0.0
    assert row_pendiente["monto_pendiente"] == 588.0
    assert row_pendiente["fecha_pago"] is None
    assert row_pendiente["numero_boleta"] == ""


@pytest.mark.asyncio
async def test_generar_lista_habilitados_con_beca():
    """Si el estudiante tiene beca, se incluye el nombre y porcentaje."""
    curso_id = ObjectId()
    est_id = ObjectId()
    beca_id = ObjectId()
    curso = _make_course(curso_id)
    enrollment = _make_enrollment(
        est_id, curso_id,
        modulos_pagados=(294.0, 0, 0, 0, 0),
        descuento_curso=0.0,
        descuento_personal=50.0,
        beca_id=beca_id
    )
    student = _make_student(est_id, nombre="Becado")
    pago = _make_payment(cantidad=294.0, inscripcion_id=enrollment.id)
    discount = MagicMock()
    discount.id = beca_id
    discount.nombre = "Beca Excelencia"

    with patch.object(payment_service, 'Course') as MockCourse, \
         patch.object(payment_service, 'Enrollment') as MockEnrollment, \
         patch.object(payment_service, 'Student') as MockStudent, \
         patch.object(payment_service, 'Payment') as MockPayment, \
         patch.object(payment_service, 'Discount') as MockDiscount, \
         patch.object(payment_service, 'In', lambda *args: MagicMock()), \
         patch('models.user.User') as MockUser:

        _setup_mocks(MockCourse, MockEnrollment, MockStudent, MockPayment, MockDiscount, MockUser,
                     curso, [enrollment], [student], [pago], descuentos=[discount])

        result = await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=1)

    assert result["rows"][0]["beca"] == "Beca Excelencia"
    assert result["rows"][0]["beca_porcentaje"] == 50.0


@pytest.mark.asyncio
async def test_generar_lista_habilitados_modulo_none_genera_registro_por_modulo():
    """Si modulo_index=None, se genera UN registro por CADA modulo (pagado o no)."""
    curso_id = ObjectId()
    est_id = ObjectId()
    curso = _make_course(curso_id, n_modulos=5)
    # Pago M1 y M2, pendiente M3-M5
    enrollment = _make_enrollment(
        est_id, curso_id,
        modulos_pagados=(588.0, 588.0, 0, 0, 0)
    )
    student = _make_student(est_id)
    pago1 = _make_payment(cantidad=588.0, fecha=datetime(2026, 7, 10), trans="BOL1", inscripcion_id=enrollment.id)
    pago2 = _make_payment(cantidad=588.0, fecha=datetime(2026, 7, 15), trans="BOL2", inscripcion_id=enrollment.id)

    with patch.object(payment_service, 'Course') as MockCourse, \
         patch.object(payment_service, 'Enrollment') as MockEnrollment, \
         patch.object(payment_service, 'Student') as MockStudent, \
         patch.object(payment_service, 'Payment') as MockPayment, \
         patch.object(payment_service, 'Discount') as MockDiscount, \
         patch.object(payment_service, 'In', lambda *args: MagicMock()), \
         patch('models.user.User') as MockUser:

        # Batch loading: una sola query trae TODOS los pagos
        _setup_mocks(MockCourse, MockEnrollment, MockStudent, MockPayment, MockDiscount, MockUser,
                     curso, [enrollment], [student], [pago1, pago2])

        result = await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=None)

    # El estudiante aparece 5 veces (1 por cada módulo)
    assert result["total_estudiantes"] == 5
    modulos = [r["modulo_index"] for r in result["rows"]]
    assert sorted(modulos) == [1, 2, 3, 4, 5]
    # M1 y M2 pagados
    rows_m1_m2 = [r for r in result["rows"] if r["modulo_index"] in (1, 2)]
    assert all(r["estado_pago"] == "PAGADO" for r in rows_m1_m2)
    # M3-M5 pendientes
    rows_m3_m5 = [r for r in result["rows"] if r["modulo_index"] in (3, 4, 5)]
    assert all(r["estado_pago"] == "PENDIENTE" for r in rows_m3_m5)
    # Total importe = 588 + 588 = 1176
    assert result["total_importe"] == 1176.0
    # Total pendiente = 588 * 3 = 1764
    assert result["total_pendiente"] == 1764.0


@pytest.mark.asyncio
async def test_generar_lista_habilitados_matricula_modulo_cero():
    """modulo_index=0 retorna solo los que pagaron matrícula."""
    curso_id = ObjectId()
    est_id = ObjectId()
    curso = _make_course(curso_id)
    enrollment = _make_enrollment(est_id, curso_id, modulos_pagados=(0, 0, 0, 0, 0))
    student = _make_student(est_id)
    pago_mat = MagicMock()
    pago_mat.estado_pago = "aprobado"
    pago_mat.cantidad_pago = 300.0
    pago_mat.numero_transaccion = "MAT-001"
    pago_mat.fecha_comprobante = datetime(2026, 6, 1)
    pago_mat.fecha_subida = datetime(2026, 6, 1)
    pago_mat.inscripcion_id = enrollment.id
    pago_mat.estudiante_id = est_id
    pago_mat.concepto = "Matrícula Diplomado IA"

    with patch.object(payment_service, 'Course') as MockCourse, \
         patch.object(payment_service, 'Enrollment') as MockEnrollment, \
         patch.object(payment_service, 'Student') as MockStudent, \
         patch.object(payment_service, 'Payment') as MockPayment, \
         patch.object(payment_service, 'Discount') as MockDiscount, \
         patch.object(payment_service, 'In', lambda *args: MagicMock()), \
         patch('models.user.User') as MockUser:

        _setup_mocks(MockCourse, MockEnrollment, MockStudent, MockPayment, MockDiscount, MockUser,
                     curso, [enrollment], [student], [pago_mat])

        result = await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=0)

    assert result["total_estudiantes"] == 1
    assert result["rows"][0]["importe"] == 300.0
    assert result["rows"][0]["numero_boleta"] == "MAT-001"


@pytest.mark.asyncio
async def test_generar_lista_habilitados_curso_no_existe():
    """Si el curso no existe, lanza ValueError."""
    with patch.object(payment_service, 'Course') as MockCourse:
        MockCourse.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="no encontrado"):
            await payment_service.generar_lista_habilitados(curso_id=ObjectId(), modulo_index=1)


@pytest.mark.asyncio
async def test_generar_lista_habilitados_modulo_fuera_de_rango():
    """Si modulo_index > N módulos del curso, lanza ValueError."""
    curso_id = ObjectId()
    curso = _make_course(curso_id, n_modulos=3)
    with patch.object(payment_service, 'Course') as MockCourse:
        MockCourse.get = AsyncMock(return_value=curso)
        with pytest.raises(ValueError, match="fuera de rango"):
            await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=10)


@pytest.mark.asyncio
async def test_generar_lista_habilitados_orden_alfabetico():
    """Las filas se devuelven ordenadas alfabéticamente por nombre."""
    curso_id = ObjectId()
    est1_id = ObjectId()
    est2_id = ObjectId()
    est3_id = ObjectId()
    curso = _make_course(curso_id)
    enr1 = _make_enrollment(est1_id, curso_id, modulos_pagados=(588.0, 0, 0, 0, 0))
    enr2 = _make_enrollment(est2_id, curso_id, modulos_pagados=(588.0, 0, 0, 0, 0))
    enr3 = _make_enrollment(est3_id, curso_id, modulos_pagados=(588.0, 0, 0, 0, 0))
    s1 = _make_student(est1_id, nombre="ZULMA")
    s2 = _make_student(est2_id, nombre="ALBERTO")
    s3 = _make_student(est3_id, nombre="MARIA")
    pago = _make_payment(cantidad=588.0, inscripcion_id=enr1.id)

    with patch.object(payment_service, 'Course') as MockCourse, \
         patch.object(payment_service, 'Enrollment') as MockEnrollment, \
         patch.object(payment_service, 'Student') as MockStudent, \
         patch.object(payment_service, 'Payment') as MockPayment, \
         patch.object(payment_service, 'Discount') as MockDiscount, \
         patch.object(payment_service, 'In', lambda *args: MagicMock()), \
         patch('models.user.User') as MockUser:

        _setup_mocks(MockCourse, MockEnrollment, MockStudent, MockPayment, MockDiscount, MockUser,
                     curso, [enr1, enr2, enr3], [s1, s2, s3], [pago])

        result = await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=1)

    nombres = [r["nombre"] for r in result["rows"]]
    assert nombres == ["ALBERTO", "MARIA", "ZULMA"]


@pytest.mark.asyncio
async def test_generar_lista_habilitados_carnet_con_complemento():
    """Si el estudiante tiene complemento_carnet, se concatena al CI."""
    curso_id = ObjectId()
    est_id = ObjectId()
    curso = _make_course(curso_id)
    enrollment = _make_enrollment(est_id, curso_id, modulos_pagados=(588.0, 0, 0, 0, 0))
    student = _make_student(est_id, carnet="1234567", complemento="1D")
    pago = _make_payment(cantidad=588.0, inscripcion_id=enrollment.id)

    with patch.object(payment_service, 'Course') as MockCourse, \
         patch.object(payment_service, 'Enrollment') as MockEnrollment, \
         patch.object(payment_service, 'Student') as MockStudent, \
         patch.object(payment_service, 'Payment') as MockPayment, \
         patch.object(payment_service, 'Discount') as MockDiscount, \
         patch.object(payment_service, 'In', lambda *args: MagicMock()), \
         patch('models.user.User') as MockUser:

        _setup_mocks(MockCourse, MockEnrollment, MockStudent, MockPayment, MockDiscount, MockUser,
                     curso, [enrollment], [student], [pago])

        result = await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=1)

    assert result["rows"][0]["ci"] == "1234567-1D"


@pytest.mark.asyncio
async def test_generar_lista_habilitados_encabezado_tipo_curso_label():
    """El tipo_label del encabezado se mapea correctamente."""
    curso_id = ObjectId()
    curso = _make_course(curso_id, tipo="maestria")
    with patch.object(payment_service, 'Course') as MockCourse, \
         patch.object(payment_service, 'Enrollment') as MockEnrollment, \
         patch.object(payment_service, 'Student') as MockStudent, \
         patch.object(payment_service, 'Payment') as MockPayment, \
         patch.object(payment_service, 'Discount') as MockDiscount, \
         patch.object(payment_service, 'In', lambda *args: MagicMock()), \
         patch('models.user.User') as MockUser:

        MockCourse.get = AsyncMock(return_value=curso)
        MockEnrollment.find = MagicMock()
        MockEnrollment.find.return_value.to_list = AsyncMock(return_value=[])
        MockStudent.find = MagicMock()
        MockStudent.find.return_value.to_list = AsyncMock(return_value=[])
        MockPayment.find = MagicMock()
        MockPayment.find.return_value.sort = MagicMock()
        MockPayment.find.return_value.sort.return_value.to_list = AsyncMock(return_value=[])
        MockDiscount.find = MagicMock()
        MockDiscount.find.return_value.to_list = AsyncMock(return_value=[])
        MockUser.find = MagicMock()
        MockUser.find.return_value.to_list = AsyncMock(return_value=[])

        result = await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=None)

    assert result["encabezado"]["programa_tipo"] == "MAESTRÍA"


@pytest.mark.asyncio
async def test_generar_lista_habilitados_orden_3_estados():
    """F-075-FIX-8: orden PAGADO -> PARCIAL -> PENDIENTE, alfabético dentro de cada grupo."""
    curso_id = ObjectId()
    est_pagado_id = ObjectId()
    est_parcial_id = ObjectId()
    est_pendiente_id = ObjectId()
    curso = _make_course(curso_id)

    enr_pagado = _make_enrollment(est_pagado_id, curso_id, modulos_pagados=(588.0, 0, 0, 0, 0))
    enr_parcial = _make_enrollment(est_parcial_id, curso_id, modulos_pagados=(294.0, 0, 0, 0, 0))
    enr_pendiente = _make_enrollment(est_pendiente_id, curso_id, modulos_pagados=(0, 0, 0, 0, 0))

    s_pagado = _make_student(est_pagado_id, nombre="ANA PAGADO")
    s_parcial = _make_student(est_parcial_id, nombre="PEDRO PARCIAL")
    s_pendiente = _make_student(est_pendiente_id, nombre="LUIS PENDIENTE")

    pago = _make_payment(cantidad=588.0, inscripcion_id=enr_pagado.id)
    pago_parcial = _make_payment(cantidad=294.0, inscripcion_id=enr_parcial.id)

    with patch.object(payment_service, 'Course') as MockCourse, \
         patch.object(payment_service, 'Enrollment') as MockEnrollment, \
         patch.object(payment_service, 'Student') as MockStudent, \
         patch.object(payment_service, 'Payment') as MockPayment, \
         patch.object(payment_service, 'Discount') as MockDiscount, \
         patch.object(payment_service, 'In', lambda *args: MagicMock()), \
         patch('models.user.User') as MockUser:

        _setup_mocks(MockCourse, MockEnrollment, MockStudent, MockPayment, MockDiscount, MockUser,
                     curso, [enr_pagado, enr_parcial, enr_pendiente],
                     [s_pagado, s_parcial, s_pendiente],
                     [pago, pago_parcial])

        result = await payment_service.generar_lista_habilitados(curso_id=curso_id, modulo_index=1)

    rows = result["rows"]
    assert len(rows) == 3
    # Primer grupo PAGADO, luego PARCIAL, luego PENDIENTE
    assert rows[0]["estado_pago"] == "PAGADO"
    assert rows[0]["nombre"] == "ANA PAGADO"
    assert rows[1]["estado_pago"] == "PARCIAL"
    assert rows[1]["nombre"] == "PEDRO PARCIAL"
    assert rows[2]["estado_pago"] == "PENDIENTE"
    assert rows[2]["nombre"] == "LUIS PENDIENTE"
