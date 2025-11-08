"""Create task command with handler."""
import time
from dataclasses import dataclass
from datetime import datetime

from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from domain.entities import Task
from domain.repositories import TaskRepository
from observability import task_processing_time, tasks_created

tracer = trace.get_tracer(__name__)


@dataclass
class CreateTaskCommand(Command[OperationResult]):
    """Command to create a new task."""
    title: str
    description: str
    priority: str = "medium"
    user_info: dict | None = None


class CreateTaskCommandHandler(CommandHandler[CreateTaskCommand, OperationResult]):
    """Handle task creation."""

    def __init__(self, task_repository: TaskRepository):
        super().__init__()
        self.task_repository = task_repository

    async def handle_async(self, command: CreateTaskCommand) -> OperationResult:
        """Handle create task command with custom instrumentation."""
        start_time = time.time()

        # Add business context to automatic span created by CQRS middleware
        add_span_attributes({
            "task.title": command.title,
            "task.priority": command.priority,
            "task.has_user_info": command.user_info is not None,
        })

        # Create custom span for task creation logic
        with tracer.start_as_current_span("create_task_entity") as span:
            # Create new task
            task = Task(
                title=command.title,
                description=command.description,
                priority=command.priority,
                status="pending",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )

            # Set creator if user info is provided
            if command.user_info:
                task.created_by = command.user_info.get("user_id")
                task.department = command.user_info.get("department")
                span.set_attribute("task.created_by", task.created_by or "unknown")
                span.set_attribute("task.department", task.department or "unknown")

        # Save task (repository operations are auto-traced)
        saved_task = await self.task_repository.add_async(task)

        # Record metrics
        processing_time_ms = (time.time() - start_time) * 1000
        tasks_created.add(1, {
            "priority": command.priority,
            "has_department": bool(command.user_info and command.user_info.get("department"))
        })
        task_processing_time.record(processing_time_ms, {
            "operation": "create",
            "priority": command.priority
        })

        return self.ok({
            "id": str(saved_task.id),
            "title": saved_task.title,
            "description": saved_task.description,
            "status": saved_task.status,
            "priority": saved_task.priority,
            "created_at": saved_task.created_at.isoformat()
        })
