"""
Servicio de Assignments (Tareas / Exámenes)
===========================================

CRUD de actividades evaluables creadas por el docente.
"""

from typing import List, Optional
from beanie import PydanticObjectId

from models.assignment import Assignment
from models.enums import AssignmentType
from schemas.classroom import AssignmentCreate, AssignmentUpdate


async def get_assignments(
    classroom_id: PydanticObjectId,
    type: Optional[AssignmentType] = None,
) -> List[Assignment]:
    query = Assignment.find(
        Assignment.classroom_id == classroom_id,
        Assignment.active == True,
    )
    if type is not None:
        query = query.find(Assignment.type == type)
    return await query.sort("-created_at").to_list()


async def get_assignment(assignment_id: PydanticObjectId) -> Optional[Assignment]:
    return await Assignment.get(assignment_id)


async def create_assignment(
    data: AssignmentCreate,
    classroom_id: PydanticObjectId,
    created_by: PydanticObjectId,
) -> Assignment:
    assignment = Assignment(
        **data.model_dump(),
        classroom_id=classroom_id,
        created_by=created_by,
    )
    await assignment.create()
    return assignment


async def update_assignment(assignment: Assignment, data: AssignmentUpdate) -> Assignment:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(assignment, field, value)
    await assignment.save()
    return assignment


async def delete_assignment(assignment_id: PydanticObjectId) -> bool:
    assignment = await Assignment.get(assignment_id)
    if not assignment:
        return False
    assignment.active = False
    await assignment.save()
    return True
