from fastapi import APIRouter
from api import students, courses, enrollments, payments

api_router = APIRouter()

api_router.include_router(students.router, prefix="/students", tags=["students"])
api_router.include_router(courses.router, prefix="/courses", tags=["courses"])
api_router.include_router(enrollments.router, prefix="/enrollments", tags=["enrollments"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
