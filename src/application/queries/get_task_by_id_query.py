"""Get task by ID query with handler."""
from dataclasses import dataclass

from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

from domain.repositories import TaskRepository


@dataclass
class GetTaskByIdQuery(Query[OperationResult]):
    """Query to retrieve a single task by ID."""
    task_id: str
    user_info: dict


class GetTaskByIdQueryHandler(QueryHandler[GetTaskByIdQuery, OperationResult]):
    """Handle task retrieval by ID with authorization checks."""

    def __init__(self, task_repository: TaskRepository):
        super().__init__()
        self.task_repository = task_repository

    async def handle_async(self, request: GetTaskByIdQuery) -> OperationResult:
        """Handle get task by ID query with RBAC logic."""
        # Retrieve task
        task = await self.task_repository.get_by_id_async(request.task_id)

        if not task:
            return self.not_found("Task", request.task_id)

        # RBAC: Check if user can view this task
        user_roles = request.user_info.get("roles", [])
        user_id = request.user_info.get("sub") or request.user_info.get("user_id")
        department = request.user_info.get("department")

        can_view = False

        if "admin" in user_roles:
            # Admins can view all tasks
            can_view = True
        elif "manager" in user_roles:
            # Managers can view tasks in their department
            if department and task.department == department:
                can_view = True
        else:
            # Regular users can only view their assigned tasks
            if user_id and task.assignee_id == user_id:
                can_view = True

        if not can_view:
            return self.bad_request("You do not have permission to view this task")

        # Convert to DTO
        task_dto = {
            "id": str(task.id),
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "priority": task.priority,
            "assignee_id": str(task.assignee_id) if task.assignee_id else None,
            "department": task.department,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat()
        }

        return self.ok(task_dto)
