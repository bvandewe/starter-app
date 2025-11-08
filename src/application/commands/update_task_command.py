"""Update task command with handler."""
import time
from dataclasses import dataclass
from datetime import datetime

from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from domain.repositories import TaskRepository
from observability import task_processing_time, tasks_completed, tasks_failed

tracer = trace.get_tracer(__name__)


@dataclass
class UpdateTaskCommand(Command[OperationResult]):
    """Command to update an existing task."""
    task_id: str
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee_id: str | None = None
    user_info: dict | None = None


class UpdateTaskCommandHandler(CommandHandler[UpdateTaskCommand, OperationResult]):
    """Handle task updates with authorization checks."""

    def __init__(self, task_repository: TaskRepository):
        super().__init__()
        self.task_repository = task_repository

    async def handle_async(self, command: UpdateTaskCommand) -> OperationResult:
        """Handle update task command with custom instrumentation."""
        start_time = time.time()

        # Add business context to automatic span
        add_span_attributes({
            "task.id": str(command.task_id),
            "task.fields_updated": sum([
                command.title is not None,
                command.description is not None,
                command.status is not None,
                command.priority is not None,
                command.assignee_id is not None,
            ]),
        })

        # Retrieve existing task (auto-traced)
        task = await self.task_repository.get_by_id_async(command.task_id)

        if not task:
            tasks_failed.add(1, {"reason": "not_found", "operation": "update"})
            return self.not_found(f"Task {command.task_id}", "Task not found")

        # Check authorization
        with tracer.start_as_current_span("check_authorization") as auth_span:
            if command.user_info:
                user_roles = command.user_info.get("roles", [])
                user_id = command.user_info.get("user_id")
                auth_span.set_attribute("user.roles", ",".join(user_roles))
                if user_id:
                    auth_span.set_attribute("user.id", str(user_id))

                # Only admin or task assignee can update
                if "admin" not in user_roles and task.assignee_id != user_id:
                    tasks_failed.add(1, {"reason": "forbidden", "operation": "update"})
                    return self.bad_request("Cannot update tasks assigned to others")

        # Update task fields
        with tracer.start_as_current_span("update_task_fields") as span:
            fields_changed = []
            if command.title is not None:
                task.title = command.title
                fields_changed.append("title")
            if command.description is not None:
                task.description = command.description
                fields_changed.append("description")
            if command.status is not None:
                old_status = task.status
                task.status = command.status
                fields_changed.append("status")
                span.set_attribute("task.status_transition", f"{old_status}->{command.status}")
            if command.priority is not None:
                task.priority = command.priority
                fields_changed.append("priority")
            if command.assignee_id is not None:
                task.assignee_id = command.assignee_id
                fields_changed.append("assignee")

            span.set_attribute("task.fields_changed", ",".join(fields_changed))
            task.updated_at = datetime.utcnow()

        # Save updated task (auto-traced)
        updated_task = await self.task_repository.update_async(task)

        # Record metrics
        processing_time_ms = (time.time() - start_time) * 1000
        task_processing_time.record(processing_time_ms, {
            "operation": "update",
            "fields_count": len(fields_changed)
        })

        # Track completion if status changed to completed
        if command.status == "completed":
            tasks_completed.add(1, {"priority": updated_task.priority})

        return self.ok({
            "id": str(updated_task.id),
            "title": updated_task.title,
            "description": updated_task.description,
            "status": updated_task.status,
            "priority": updated_task.priority,
            "updated_at": updated_task.updated_at.isoformat()
        })
