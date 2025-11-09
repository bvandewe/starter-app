"""Create task command with handler."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import (
    CloudEventPublishingOptions,
)
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from application.events.integration.task_events import TaskCreatedIntegrationEventV1
from domain.entities import Task
from domain.enums import TaskPriority, TaskStatus
from domain.repositories import TaskRepository
from integration.models.task_dto import TaskCreatedDto
from observability import task_processing_time, tasks_created

from .command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class CreateTaskCommand(Command[OperationResult[TaskCreatedDto]]):
    """Command to create a new task."""

    title: str
    description: str
    priority: TaskPriority = TaskPriority.MEDIUM
    user_info: dict | None = None


class CreateTaskCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateTaskCommand, OperationResult[TaskCreatedDto]],
):
    """Handle task creation."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        task_repository: TaskRepository,
    ):
        super().__init__(
            mediator,
            mapper,
            cloud_event_bus,
            cloud_event_publishing_options,
        )
        self.task_repository = task_repository

    async def handle_async(
        self, request: CreateTaskCommand
    ) -> OperationResult[TaskCreatedDto]:
        """Handle create task command with custom instrumentation."""
        command = request
        start_time = time.time()

        # Add business context to automatic span created by CQRS middleware
        add_span_attributes(
            {
                "task.title": command.title,
                "task.priority": command.priority,
                "task.has_user_info": command.user_info is not None,
            }
        )

        # Create custom span for task creation logic
        with tracer.start_as_current_span("create_task_entity") as span:
            # Create new task
            task = Task(
                title=command.title,
                description=command.description,
                priority=command.priority,
                status=TaskStatus.PENDING,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
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
        tasks_created.add(
            1,
            {
                "priority": command.priority,
                "has_department": bool(
                    command.user_info and command.user_info.get("department")
                ),
            },
        )
        task_processing_time.record(
            processing_time_ms, {"operation": "create", "priority": command.priority}
        )

        ev = TaskCreatedIntegrationEventV1(
            aggregate_id=saved_task.id,
            created_at=saved_task.created_at,
            title=saved_task.title,
            description=saved_task.description,
            status=saved_task.status,
            priority=saved_task.priority,
            assignee_id=saved_task.assignee_id,
            department=saved_task.department,
        )
        await self.publish_cloud_event_async(ev)
        log.debug(f"Published cloud event for task creation: {ev.aggregate_id}")

        return self.ok(self.mapper.map(saved_task, TaskCreatedDto))
