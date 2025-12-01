from fastapi import APIRouter
from api import students, courses, enrollments, payments, discounts, users, auth

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(students.router, prefix="/students", tags=["students"])
api_router.include_router(courses.router, prefix="/courses", tags=["courses"])
api_router.include_router(enrollments.router, prefix="/enrollments", tags=["enrollments"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(discounts.router, prefix="/discounts", tags=["discounts"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
