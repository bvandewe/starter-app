"""
Task event handlers for Mario's Pizzeria.

These handlers process task-related domain events to implement side effects like
notifications, kitchen updates, delivery tracking, customer communications,
customer active order management, and customer notification creation.
"""

import logging

from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import (
    CloudEventPublishingOptions,
)
from neuroglia.mediation import DomainEventHandler, Mediator

from application.events.domain.domain_event_handler_base import DomainEventHandlerBase
from domain.events import TaskCreatedDomainEvent

# Set up logger
logger = logging.getLogger(__name__)


class TaskCreatedDomainEventHandler(
    DomainEventHandlerBase[TaskCreatedDomainEvent],
    DomainEventHandler[TaskCreatedDomainEvent],
):
    """Handles task created events - sends notifications and updates task status"""

    def __init__(
        self,
        mediator: Mediator,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
    ):
        super().__init__(mediator, cloud_event_bus, cloud_event_publishing_options)

    async def handle_async(self, event: TaskCreatedDomainEvent) -> None:
        """Process task created event"""
        logger.info(f"Task '{event.aggregate_id}':'{event.title}' created!")
        # Publish cloud event for external integrations
        await self.publish_cloud_event_async(event)
        return None
