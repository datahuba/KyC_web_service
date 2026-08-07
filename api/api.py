from fastapi import APIRouter
from api import students, courses, enrollments, payments, discounts, users, auth, payment_config, classroom, notifications, account_requests, passive_requests, bank_statements, enrollment_requests, dashboard, pre_registrations, admin, admin_data_health, certificates, reports, tramite_solicitudes, comunicados  # F-CERTIFICADOS (2026-07-29); F-CUENTAS-POR-COBRAR (2026-07-29); F-TRAMITES-SOLICITUD (2026-07-29); US-003 (2026-08-03): Comunicados; R35-FASE-3 (2026-08-07): Reporte consolidado transversal

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(students.router, prefix="/students", tags=["students"])
api_router.include_router(courses.router, prefix="/courses", tags=["courses"])
api_router.include_router(enrollments.router, prefix="/enrollments", tags=["enrollments"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(payment_config.router, prefix="/payment-config", tags=["payment-config"])
api_router.include_router(discounts.router, prefix="/discounts", tags=["discounts"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(classroom.router, prefix="/classroom", tags=["classroom"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(account_requests.router, prefix="/account-requests", tags=["account-requests"])
api_router.include_router(passive_requests.router, prefix="/passive-requests", tags=["passive-requests"])
api_router.include_router(bank_statements.router, prefix="/bank-statements", tags=["bank-statements"])
api_router.include_router(enrollment_requests.router, prefix="/enrollment-requests", tags=["enrollment-requests"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
# ISSUE-Q-PRE-REGISTRO-FORM (2026-07-17): formularios dinámicos de pre-inscripción.
api_router.include_router(pre_registrations.router, prefix="/pre-registrations", tags=["pre-registrations"])
# F-044 (2026-07-22): visor de errores 500 para admin/superadmin.
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
# R35-FASE-3 (2026-08-07, Kevin): reporte consolidado de inconsistencias de datos
api_router.include_router(admin_data_health.router, prefix="/admin", tags=["admin-data-health"])
# F-CERTIFICADOS (2026-07-29): emisión de Certificados de Notas y No Deudor.
api_router.include_router(certificates.router, prefix="/certificates", tags=["certificates"])
# F-TRAMITES-SOLICITUD (2026-07-29): solicitudes de Convalidación, Tutoría,
# Readmisión y Titulación que el estudiante crea desde /app/requests.
api_router.include_router(tramite_solicitudes.router, prefix="/tramites", tags=["tramites"])
# F-CUENTAS-POR-COBRAR (2026-07-29): reporte de CxC real vs estimada.
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
# US-003 (2026-08-03): Comunicados. Anuncios oficiales del personal a estudiantes
# con pop-up al primer login. Audiencia: solo estudiantes.
api_router.include_router(comunicados.router, prefix="/comunicados", tags=["comunicados"])
