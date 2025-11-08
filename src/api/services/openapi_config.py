"""OpenAPI/Swagger configuration service for API documentation."""
from typing import Any, cast

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from application.settings import Settings


def _resolve_mount_prefix(app: FastAPI) -> str:
    """Return the normalized mount prefix ('' when mounted at root)."""
    prefix = getattr(app.state, "openapi_path_prefix", "")
    if not prefix:
        return ""
    normalized = prefix if prefix.startswith("/") else f"/{prefix}"
    normalized = normalized.rstrip("/")
    return normalized


# Custom setup function for API sub-app OpenAPI configuration
def configure_api_openapi(
    app: FastAPI, settings: Settings
) -> None:
    """Configure OpenAPI security schemes for the API sub-app."""
    OpenAPIConfigService.configure_security_schemes(
        app, settings
    )
    OpenAPIConfigService.configure_swagger_ui(app, settings)


class OpenAPIConfigService:
    """Service to configure OpenAPI schema with security schemes for Swagger UI."""

    @staticmethod
    def configure_security_schemes(
        app: FastAPI,
        settings: Settings,
    ) -> None:
        """Configure OpenAPI security schemes for authentication in Swagger UI.

        Adds OAuth2 Authorization Code flow for browser-based authentication
        via Keycloak. Users click "Authorize" in Swagger UI, login via Keycloak,
        and the access token is automatically included in API requests.

        The client_id is automatically populated from settings.KEYCLOAK_CLIENT_ID,
        while client_secret is left empty for users to provide if needed.

        Args:
            app: FastAPI application instance
            settings: Application settings with Keycloak configuration
        """

        def custom_openapi() -> dict[str, Any]:
            """Generate custom OpenAPI schema with security configurations."""
            if app.openapi_schema:
                return app.openapi_schema

            openapi_schema = get_openapi(
                title=app.title,
                version=app.version,
                description=app.description,
                routes=app.routes,
            )

            # Add security scheme for OAuth2 Authorization Code Flow
            if "components" not in openapi_schema:
                openapi_schema["components"] = {}
            if "securitySchemes" not in openapi_schema["components"]:
                openapi_schema["components"]["securitySchemes"] = {}

            openapi_schema["components"]["securitySchemes"]["oauth2"] = {
                "type": "oauth2",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/auth",
                        "tokenUrl": f"{settings.keycloak_url_internal}/realms/{settings.keycloak_realm}/protocol/openid-connect/token",
                        "scopes": {
                            "openid": "OpenID Connect",
                            "profile": "User profile",
                            "email": "Email address",
                            "roles": "User roles",
                        },
                    }
                },
            }

            # Apply security scheme to all operations
            openapi_schema["security"] = [{"oauth2": ["openid", "profile", "email", "roles"]}]

            # Set client_id in Swagger UI
            if "swagger-ui-parameters" not in openapi_schema:
                openapi_schema["swagger-ui-parameters"] = {}
            openapi_schema["swagger-ui-parameters"]["client_id"] = settings.keycloak_client_id

            app.openapi_schema = openapi_schema
            return app.openapi_schema

        app.openapi = custom_openapi  # type: ignore

    @staticmethod
    def configure_swagger_ui(app: FastAPI, settings: Settings) -> None:
        """Configure Swagger UI with OAuth2 client credentials.

        This sets up the Swagger UI initOAuth parameters to pre-fill
        the client_id in the authorization dialog.

        Args:
            app: FastAPI application instance
            settings: Application settings with Keycloak configuration
        """
        # Override swagger_ui_init_oauth to provide client_id
        # Prefer public browser client if configured (avoids confidential secret exposure)
        public_client_id = cast(str, getattr(settings, "KEYCLOAK_PUBLIC_CLIENT_ID", ""))
        confidential_client_id = cast(str, getattr(settings, "KEYCLOAK_CLIENT_ID", ""))
        client_secret = cast(str, getattr(settings, "KEYCLOAK_CLIENT_SECRET", ""))

        chosen_client_id = public_client_id or confidential_client_id

        # Configure OAuth init; pass clientSecret only if using confidential client
        init_oauth: dict[str, Any] = {
            "clientId": chosen_client_id,
            "usePkceWithAuthorizationCodeGrant": True,
        }
        if chosen_client_id == confidential_client_id and client_secret:
            init_oauth["clientSecret"] = client_secret

        app.swagger_ui_init_oauth = init_oauth

        # Persist tokens across doc reloads and highlight server prefix in the UI
        existing_params = getattr(app, "swagger_ui_parameters", None)
        if not isinstance(existing_params, dict):
            existing_params = {}
        app.swagger_ui_parameters = {
            **existing_params,
            "persistAuthorization": True,
            # Ensure requests get Authorization header when flow completes
            # FastAPI's Swagger UI auto-injects once token is stored; we just keep it.
        }
