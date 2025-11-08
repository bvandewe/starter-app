"""Main application entry point with SubApp mounting."""

import logging
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from neuroglia.data.infrastructure.mongo import MotorRepository
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_ingestor import (
    CloudEventIngestor,
)
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_middleware import (
    CloudEventMiddleware,
)
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import (
    CloudEventPublisher,
)
from neuroglia.hosting.web import SubAppConfig, WebApplicationBuilder
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.observability import Observability
from neuroglia.serialization.json import JsonSerializer
from starlette.responses import Response
from starlette.routing import Mount

from api.services import AuthService
from api.services.openapi_config import configure_api_openapi
from application.services import configure_logging
from application.settings import app_settings
from domain.entities import Task
from domain.repositories import TaskRepository
from infrastructure import InMemorySessionStore, RedisSessionStore, SessionStore
from integration.repositories.motor_task_repository import MongoTaskRepository

configure_logging(log_level=app_settings.log_level)
log = logging.getLogger(__name__)


def create_session_store() -> SessionStore:
    """Factory function to create SessionStore based on configuration.

    Returns:
        InMemorySessionStore for development (sessions lost on restart)
        RedisSessionStore for production (distributed, persistent sessions)
    """
    if app_settings.redis_enabled:
        log.info(f"🔴 Using RedisSessionStore (url={app_settings.redis_url})")
        try:
            store = RedisSessionStore(
                redis_url=app_settings.redis_url,
                session_timeout_hours=app_settings.session_timeout_hours,
                key_prefix=app_settings.redis_key_prefix,
            )
            # Test connection
            if store.ping():
                log.info("✅ Redis connection successful")
            else:
                log.warning("⚠️ Redis ping failed - sessions may not persist")
            return store
        except Exception as e:
            log.error(f"❌ Failed to connect to Redis: {e}")
            log.warning("⚠️ Falling back to InMemorySessionStore")
            return InMemorySessionStore(
                session_timeout_hours=app_settings.session_timeout_hours
            )
    else:
        log.info("💾 Using InMemorySessionStore (development only)")
        return InMemorySessionStore(
            session_timeout_hours=app_settings.session_timeout_hours
        )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Creates separate apps for:
    - API backend (/api prefix) - REST API for task management
    - UI frontend (/ prefix) - Web interface

    Returns:
        Configured FastAPI application with multiple mounted apps
    """
    log.info("🚀 Creating Simple UI application...")

    builder = WebApplicationBuilder(app_settings=app_settings)

    # Configure core services
    Mediator.configure(
        builder,
        [
            "application.commands",
            "application.queries",
            "application.events.integration",
        ],
    )
    Mapper.configure(
        builder,
        [
            "application.commands",
            "application.queries",
            "application.mapping",
            "integration.models",
        ],
    )
    JsonSerializer.configure(
        builder,
        [
            "domain.entities",
            "domain.models",
            "integration.models",
        ],
    )
    CloudEventPublisher.configure(builder)
    CloudEventIngestor.configure(builder, ["application.events.integration"])
    Observability.configure(builder)

    # Configure MongoDB repository
    MotorRepository.configure(
        builder,
        entity_type=Task,
        key_type=str,
        database_name="starter_app",
        collection_name="tasks",
    )

    # Configure services
    services = builder.services

    # Register repositories - MongoTaskRepository with dependency injection
    services.add_scoped(TaskRepository, MongoTaskRepository)

    # Register infrastructure services - use factory to create appropriate session store
    session_store = create_session_store()
    services.add_singleton(SessionStore, singleton=session_store)

    # Register API services
    # Create AuthService instance (will be shared by both DI and middleware)
    auth_service_instance = AuthService(session_store)
    # Pre-warm JWKS cache (ignore failure silently; will retry on first token usage)
    try:
        auth_service_instance._fetch_jwks()
        log.info("🔐 JWKS cache pre-warmed")
    except Exception as e:
        log.debug(f"JWKS pre-warm skipped: {e}")
    services.add_singleton(AuthService, singleton=auth_service_instance)

    # Add SubApp for API with controllers
    builder.add_sub_app(
        SubAppConfig(
            path="/api",
            name="api",
            title=f"{app_settings.app_name} API",
            description="Task management REST API with OAuth2/JWT authentication",
            version=app_settings.app_version,
            controllers=["api.controllers"],
            custom_setup=lambda app, service_provider: configure_api_openapi(
                app,
                app_settings,
            ),
            docs_url="/docs",
        )
    )

    # UI sub-app: Web interface serving static files built by Parcel
    # Get absolute path to static directory
    static_dir = Path(__file__).parent.parent / "static"

    # Add SubApp for UI at root path
    builder.add_sub_app(
        SubAppConfig(
            path="/",
            name="ui",
            title=app_settings.app_name,
            controllers=["ui.controllers"],
            static_files={"/static": str(static_dir)},
            docs_url=None,  # Disable docs for UI
        )
    )

    # Build the application
    app = builder.build_app_with_lifespan(
        title="Starter App",
        description="Task management application with multi-app architecture",
        version="1.0.0",
        debug=True,
    )

    # Annotate mounted sub-apps with their mount path so Swagger can render full URLs
    for route in app.routes:
        if isinstance(route, Mount) and hasattr(route, "app") and route.app is not None:
            mount_path = route.path or ""
            # Normalize to leading slash, but treat root mount as empty prefix
            if mount_path and not mount_path.startswith("/"):
                mount_path = f"/{mount_path}"
            normalized_prefix = (
                mount_path.rstrip("/") if mount_path not in ("", "/") else ""
            )
            route.app.state.openapi_path_prefix = normalized_prefix  # type: ignore[attr-defined]

    # Add middleware to inject AuthService into request state for FastAPI dependencies
    # Use the same instance that's registered in the DI container
    @app.middleware("http")
    async def inject_auth_service(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Middleware to inject AuthService into FastAPI request state.

        This middleware injects the AuthService instance into request state
        so FastAPI dependencies can access it. We use the same instance that's
        registered in Neuroglia's DI container for consistency.
        """
        # Use the auth_service_instance from module scope (same one in DI container)
        request.state.auth_service = auth_service_instance
        response = await call_next(request)
        return response

    app.add_middleware(CloudEventMiddleware, service_provider=app.state.services)

    if app_settings.enable_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    log.info("✅ Application created successfully!")
    log.info("📊 Access points:")
    log.info("   - UI: http://localhost:8020/")
    log.info("   - API Docs: http://localhost:8020/api/docs")
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:create_app",
        factory=True,
        host=app_settings.app_host,
        port=app_settings.app_port,
        reload=app_settings.debug,
    )
