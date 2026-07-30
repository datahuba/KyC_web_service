"""
Backfill de Módulo 1 como 'iniciado'
====================================

F-CUENTAS-POR-COBRAR (2026-07-29): para que la nueva métrica de CxC real
funcione sin perder la deuda actualmente visible, marcamos automáticamente
como 'iniciado_en = fecha_inscripcion' el Módulo 1 (índice 0) de todos los
enrollments activos. Los módulos 2..N quedan en None; Sandra/Rocío los irá
iniciando manualmente con el click del nuevo botón en el kardex.

ENROLLS EXCLUIDOS (no se tocan, no cuentan para CxC):
- estado in {SUSPENDIDO, RETIRADO, CANCELADO} (pasivos, abandonados, retirados)
- estado in {COMPLETADO} (programa ya finalizado)

USO:
    # Dry-run (default, recomendado): muestra el plan sin tocar la BD
    .venv\Scripts\python.exe scripts/backfill_modulo_iniciado.py

    # Aplicar: ejecuta el backfill de verdad
    .venv\Scripts\python.exe scripts/backfill_modulo_iniciado.py --apply

    # Aplicar y limitar el lote (para deployar incrementalmente)
    .venv\Scripts\python.exe scripts/backfill_modulo_iniciado.py --apply --limit 200
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Forzar UTF-8 en stdout para Windows (cp1252 no soporta emojis)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Permitir ejecutar desde KyC_web_service/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import motor.motor_asyncio
from beanie import init_beanie
from core.config import settings

# Importar todos los modelos para que Beanie los registre (igual que core/database.py)
from models.user import User
from models.student import Student
from models.course import Course
from models.enrollment import Enrollment, ModuloEstado
from models.payment import Payment
from models.payment_config import PaymentConfig
from models.discount import Discount
from models.classroom import Classroom, ClassroomStudent
from models.classroom_material import ClassroomMaterial
from models.assignment import Assignment
from models.submission import Submission
from models.notification import Notification
from models.account_request import AccountRequest
from models.passive_request import PassiveRequest
from models.bank_statement_entry import BankStatementEntry
from models.enrollment_request import EnrollmentRequest
from models.pre_registration import PreRegistrationForm, PreRegistration
from models.error_log import ErrorLog
from models.certificate import Certificate
from models.certificate_counter import CertificateCounter

from models.enums import EstadoInscripcion


DOCUMENT_MODELS = [
    User, Student, Notification, AccountRequest, PassiveRequest,
    BankStatementEntry, EnrollmentRequest, PreRegistrationForm, PreRegistration,
    Course, Enrollment, Payment, PaymentConfig, Discount,
    Classroom, ClassroomStudent, ClassroomMaterial, Assignment, Submission,
    ErrorLog, Certificate, CertificateCounter,
]


# Estados que EXCLUIMOS del backfill (no cuentan para CxC real)
ESTADOS_EXCLUIDOS = {
    EstadoInscripcion.SUSPENDIDO,
    EstadoInscripcion.RETIRADO,
    EstadoInscripcion.CANCELADO,
    EstadoInscripcion.COMPLETADO,  # ya finalizado, no aporta a CxC
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill del Módulo 1 como 'iniciado' para CxC real"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Ejecuta el backfill (default: dry-run, solo muestra el plan)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Máximo de enrollments a tocar (útil para deployar incremental)",
    )
    return parser.parse_args()


async def run(apply: bool, limit: int | None) -> int:
    print(f"🔌 Conectando a MongoDB: db={settings.DATABASE_NAME}")
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.DATABASE_NAME]
    await init_beanie(database=db, document_models=DOCUMENT_MODELS)

    print(f"\n{'=' * 70}")
    print(f"{'APLICANDO BACKFILL' if apply else 'DRY-RUN (no se modifica nada)'}")
    print(f"{'=' * 70}\n")

    # 1. Total de enrollments candidatos
    total_enrollments = await Enrollment.find_all().count()
    print(f"📊 Enrollments totales en BD: {total_enrollments}")

    # 2. Enrollments a tocar (estado NOT in excluidos, tienen modulos no vacío)
    estados_incluidos = [e for e in EstadoInscripcion if e not in ESTADOS_EXCLUIDOS]
    query = {
        "estado": {"$in": [e.value for e in estados_incluidos]},
        "modulos.0": {"$exists": True},
    }
    candidatos = await Enrollment.find(query).to_list()
    print(f"📊 Enrollments candidatos (estado activo + con módulos): {len(candidatos)}")

    # 3. De esos, cuáles ya tienen el módulo 1 iniciado (no-op)
    ya_iniciados = sum(
        1 for e in candidatos if e.modulos and e.modulos[0].iniciado_en is not None
    )
    print(f"📊 Ya tienen Módulo 1 iniciado: {ya_iniciados}")
    a_tocar = len(candidatos) - ya_iniciados
    print(f"📊 A backfillar: {a_tocar}")

    if limit:
        print(f"📊 Límite aplicado: {limit} (se procesarán {min(limit, a_tocar)})")
        a_tocar = min(limit, a_tocar)

    # 4. Preview
    print(f"\n{'=' * 70}")
    print("PREVIEW (primeros 5)")
    print(f"{'=' * 70}\n")
    for e in candidatos[:5]:
        m0 = e.modulos[0] if e.modulos else None
        fecha = m0.iniciado_en if m0 else None
        if fecha and limit is None and not apply:
            continue  # ya estaba iniciado
        print(
            f"  enrollment {e.id} | estado={e.estado} | "
            f"curso={e.curso_id} | M1.iniciado_en: {fecha or 'None → backfill'}"
        )

    if not apply:
        print(
            f"\n⚠️  DRY-RUN: no se modificó nada. "
            f"Ejecuta con --apply para backfillar {a_tocar} enrollments."
        )
        return 0

    # 5. Aplicar
    print(f"\n{'=' * 70}")
    print("APLICANDO")
    print(f"{'=' * 70}\n")

    tocados = 0
    errores = 0
    for e in candidatos:
        if limit and tocados >= limit:
            break
        m0 = e.modulos[0] if e.modulos else None
        if m0 is None or m0.iniciado_en is not None:
            continue  # ya estaba, skip
        try:
            m0.iniciado_en = e.fecha_inscripcion or datetime.utcnow()
            await e.save()
            tocados += 1
        except Exception as ex:
            errores += 1
            print(f"  ✗ enrollment {e.id}: {ex}")

    print(f"\n✅ Backfill completado: {tocados} modificados, {errores} errores")
    return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(run(apply=args.apply, limit=args.limit))


if __name__ == "__main__":
    sys.exit(main())
