"""
Order event handlers for Mario's Pizzeria.

These handlers process order-related domain events to implement side effects like
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
from domain.events import UserLoggedInDomainEvent

log = logging.getLogger(__name__)


class UserLoggedInDomainEventHandler(
    DomainEventHandlerBase[UserLoggedInDomainEvent],
    DomainEventHandler[UserLoggedInDomainEvent],
):
    """Handles user logged in events - creates user session and sends welcome notification"""

    def __init__(
        self,
        mediator: Mediator,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
    ):
        super().__init__(mediator, cloud_event_bus, cloud_event_publishing_options)

    async def handle_async(self, event: UserLoggedInDomainEvent) -> None:
        """Process user logged in event"""
        log.info(f"👤 User {event.username} logged in!")
        # Publish cloud event for external integrations
        await self.publish_cloud_event_async(event)
        return None
