"""
Domain events for Task Operations

These events represent important business occurrences that have happened in the past
and may trigger side effects like notifications, logging, or updating read models.
"""

from dataclasses import dataclass
from datetime import datetime

from neuroglia.data.abstractions import DomainEvent
from neuroglia.eventing.cloud_events.decorators import cloudevent

from domain.enums import TaskPriority, TaskStatus


@cloudevent("task.created.v1")
@dataclass
class TaskCreatedDomainEvent(DomainEvent):
    """Event raised when a new task is created."""

    def __init__(self, aggregate_id: str, title: str, description: str):
        super().__init__(aggregate_id)
        self.title = title
        self.description = description

    aggregate_id: str
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    assignee_id: str
    department: str
    created_at: datetime
    updated_at: datetime
    created_by: str
