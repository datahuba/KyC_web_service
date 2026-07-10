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
    
    # 3. Enrollments
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
