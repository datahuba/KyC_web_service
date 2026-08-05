from fastapi import APIRouter, Depends
from models.user import User
from models.student import Student
from models.course import Course
from models.enrollment import Enrollment
from models.payment import Payment
from api.dependencies import require_staff

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats(current_user: User = Depends(require_staff)):
    """
    Get aggregate stats for the admin dashboard.
    """
    # Base query filters based on user's assigned courses if they are segmented
    course_query = {}
    if current_user.cursos_asignados:
        course_query = {"_id": {"$in": current_user.cursos_asignados}}
    
    # 1. Courses
    courses_total = await Course.find(course_query).count()
    courses_active = await Course.find(course_query, Course.activo == True).count()
    
    # If the user is restricted by courses, we need to filter students, enrollments and payments by those courses
    enrollment_query = {}
    payment_query = {}
    student_query = {}
    
    if current_user.cursos_asignados:
        enrollment_query = {"curso_id": {"$in": current_user.cursos_asignados}}
        payment_query = {"curso_id": {"$in": current_user.cursos_asignados}}
        student_query = {"lista_cursos_ids": {"$in": current_user.cursos_asignados}}
    
    # 2. Students
    students_total = await Student.find(student_query).count()
    students_active = await Student.find(student_query, Student.activo == True).count()

    # F-R35-DASHBOARD-HUERFANOS (2026-08-04): cuando Kevin elimina un programa
    # y lo crea de nuevo, los enrollments del curso viejo SIGUEN en la BD
    # pero el curso ya no existe. Esto inflaba el conteo de inscritos.
    # Filtramos enrollments cuyo curso_id exista en la coleccion Course.
    cursos_visibles = await Course.find().to_list()
    curso_ids_visibles = [c.id for c in cursos_visibles]
    # F-CXC-EXCLUIR-HISTORICOS (2026-08-04, Kevin): tambien excluimos los
    # programas historicos del dashboard. Esos son de carga retroactiva/
    # auditoria, no se les cobra, no deben contar como "inscritos activos".
    curso_ids_historicos = {c.id for c in cursos_visibles if getattr(c, "es_historico", False)}
    if curso_ids_visibles:
        if enrollment_query and "curso_id" in enrollment_query:
            # Merge con cursos_asignados si existe (segmentacion)
            existing = enrollment_query["curso_id"]
            if isinstance(existing, dict) and "$in" in existing:
                # Mantener solo cursos visibles Y no historicos
                enrollment_query["curso_id"]["$in"] = [
                    cid for cid in existing["$in"] if cid in curso_ids_visibles and cid not in curso_ids_historicos
                ]
        else:
            enrollment_query = {"curso_id": {"$in": [cid for cid in curso_ids_visibles if cid not in curso_ids_historicos]}}

    # Tambien excluir historicos del conteo de pagos pendientes? NO:
    # los pagos ya cobrados de historicos son dinero real (total_ingresos),
    # deben contar. Solo excluimos los enrollments.

    # 3. Enrollments (solo de cursos visibles)
    enrollments_total = await Enrollment.find(enrollment_query).count()
    enrollments_active = await Enrollment.find(enrollment_query, Enrollment.estado == "activo").count()
    
    # 4. Payments
    payments_total = await Payment.find(payment_query).count()
    payments_pending = await Payment.find(payment_query, Payment.estado_pago == "pendiente").count()
    
    payments_revenue = 0
    pipeline = []
    if payment_query:
        pipeline.append({"$match": payment_query})
    else:
        pipeline.append({"$match": {}})
        
    pipeline.append({
        "$match": {
            "estado_pago": {"$in": ["aprobado", "pagado"]}
        }
    })
    pipeline.append({
        "$group": {
            "_id": None,
            "total": {"$sum": "$cantidad_pago"}
        }
    })
    
    revenue_result = await Payment.aggregate(pipeline).to_list()
    if revenue_result:
        payments_revenue = revenue_result[0]["total"]
    
    return {
        "students": {
            "total": students_total,
            "active": students_active
        },
        "courses": {
            "total": courses_total,
            "active": courses_active
        },
        "enrollments": {
            "total": enrollments_total,
            "active": enrollments_active
        },
        "payments": {
            "total": payments_total,
            "pending": payments_pending,
            "revenue": payments_revenue
        }
    }
