import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, IndexModel


COLLECTIONS = [
    "classrooms",
    "classroom_students",
    "classroom_materials",
    "assignments",
    "submissions",
]


async def ensure_collection(db, name: str):
    existing = await db.list_collection_names()
    if name not in existing:
        await db.create_collection(name)
        print(f"[CREATED] {name}")
    else:
        print(f"[OK] {name}")


async def create_indexes(db):
    await db["classrooms"].create_indexes([
        IndexModel([("course_id", ASCENDING)], name="idx_classrooms_course"),
        IndexModel([("teacher_user_id", ASCENDING)], name="idx_classrooms_teacher"),
        IndexModel([("active", ASCENDING)], name="idx_classrooms_active"),
    ])

    await db["classroom_students"].create_indexes([
        IndexModel([("classroom_id", ASCENDING)], name="idx_cls_students_classroom"),
        IndexModel([("student_id", ASCENDING)], name="idx_cls_students_student"),
        IndexModel(
            [("classroom_id", ASCENDING), ("student_id", ASCENDING)],
            unique=True,
            name="uq_classroom_student"
        ),
    ])

    await db["classroom_materials"].create_indexes([
        IndexModel([("classroom_id", ASCENDING)], name="idx_materials_classroom"),
        IndexModel([("uploaded_by", ASCENDING)], name="idx_materials_uploaded_by"),
        IndexModel([("created_at", DESCENDING)], name="idx_materials_created_at"),
    ])

    await db["assignments"].create_indexes([
        IndexModel([("classroom_id", ASCENDING)], name="idx_assignments_classroom"),
        IndexModel([("type", ASCENDING)], name="idx_assignments_type"),  # TASK | EXAM
        IndexModel([("due_at", ASCENDING)], name="idx_assignments_due_at"),
        IndexModel([("created_by", ASCENDING)], name="idx_assignments_created_by"),
    ])

    await db["submissions"].create_indexes([
        IndexModel([("assignment_id", ASCENDING)], name="idx_submissions_assignment"),
        IndexModel([("student_id", ASCENDING)], name="idx_submissions_student"),
        IndexModel([("classroom_id", ASCENDING)], name="idx_submissions_classroom"),
        IndexModel(
            [("assignment_id", ASCENDING), ("student_id", ASCENDING)],
            unique=True,
            name="uq_submission_assignment_student"
        ),
    ])

    print("[OK] Indexes created/verified")


async def main():
    mongo_url = os.environ["MONGODB_URL"]
    db_name = os.environ.get("DATABASE_NAME", "KyC")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    for c in COLLECTIONS:
        await ensure_collection(db, c)

    await create_indexes(db)

    print("\nDone.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())