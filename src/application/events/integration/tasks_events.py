import datetime
import logging
from dataclasses import dataclass, field
from uuid import uuid4

from neuroglia.eventing.cloud_events.decorators import cloudevent
from neuroglia.integration.models import IntegrationEvent

log = logging.getLogger(__name__)


@cloudevent("task.created.v1")
@dataclass
class TaskCreatedIntegrationEventV1(IntegrationEvent[str]):
    aggregate_id: str
    """The unique id of the Event (copied from the Task.id, required by IntegrationEvent)."""

    created_at: datetime.datetime
    """The timestamp when the task was created."""

    id: str = field(default_factory=lambda: str(uuid4()))
    """The unique id of the Task."""

    title: str = ""
    """The title of the Task."""

    description: str = ""
    """The description of the Task."""

    status: str = "pending"
    """The status of the Task."""

    priority: str = "medium"
    """The priority of the Task."""

    assignee_id: str | None = None
    """The id of the user assigned to the Task."""

    department: str | None = None
    """The department responsible for the Task."""
