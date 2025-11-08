"""Authentication API controller with OAuth2/OIDC flow."""
import secrets
from typing import Optional

import jwt
from classy_fastapi.decorators import get, post
from fastapi import Cookie, HTTPException, status
from fastapi.responses import RedirectResponse
from keycloak import KeycloakOpenID
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase

from application.settings import app_settings
from infrastructure import SessionStore


class AuthController(ControllerBase):
    """Portable Controller for OAuth2/OIDC authentication with Keycloak.

    Flow:
    1. User clicks login → GET /api/auth/login → Redirect to Keycloak
    2. User enters credentials at Keycloak
    3. Keycloak redirects → GET /api/auth/callback?code=xxx
    4. Backend exchanges code for tokens
    5. Backend creates session, sets httpOnly cookie
    6. User accesses app with cookie automatically sent
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        super().__init__(service_provider, mapper, mediator)

        # Initialize Keycloak client with CONFIDENTIAL backend client
        # This client has client_secret for secure token exchange
        self.keycloak = KeycloakOpenID(
            server_url=app_settings.keycloak_url_internal,
            client_id=app_settings.keycloak_client_id,
            realm_name=app_settings.keycloak_realm,
            client_secret_key=app_settings.keycloak_client_secret
        )

        # Get session store from DI container as Controllers cant define additional dependencies
        session_store = service_provider.get_service(SessionStore)
        if session_store is None:
            raise RuntimeError("SessionStore not found in service provider")
        self.session_store: SessionStore = session_store

    @get("/login")
    async def login(self):
        """Initiate OAuth2 login - redirect user to Keycloak login page.

        Returns:
            Redirect to Keycloak authorization endpoint
        """
        # Generate state parameter for CSRF protection
        state = secrets.token_urlsafe(16)

        # Build Keycloak authorization URL
        # Note: Request roles scope to include user roles in token/userinfo
        auth_url = self.keycloak.auth_url(
            redirect_uri=f"{app_settings.app_url}/api/auth/callback",
            scope="openid profile email roles",
            state=state
        )

        return RedirectResponse(url=auth_url)

    @get("/callback")
    async def callback(
        self,
        code: str,
        state: str
    ):
        """Handle OAuth2 callback from Keycloak.

        Args:
            code: Authorization code from Keycloak
            state: CSRF protection token

        Returns:
            Redirect to application home page with session cookie set
        """
        try:
            # Exchange authorization code for tokens
            tokens = self.keycloak.token(
                grant_type="authorization_code",
                code=code,
                redirect_uri=f"{app_settings.app_url}/api/auth/callback"
            )

            # Get user information using access token
            user_info = self.keycloak.userinfo(tokens['access_token'])

            # Extract roles from access token
            # Note: Keycloak includes roles in access token's realm_access claim,
            # but userinfo endpoint may not return them by default
            try:
                # Decode access token to extract realm roles (already validated by Keycloak)
                access_token_decoded = jwt.decode(
                    tokens['access_token'],
                    options={"verify_signature": False}
                )

                # Get realm roles from token
                realm_roles = access_token_decoded.get('realm_access', {}).get('roles', [])

                # Add roles to user_info if present in token
                if realm_roles:
                    # Filter out default Keycloak roles (offline_access, uma_authorization)
                    user_roles = [
                        role for role in realm_roles
                        if role not in ['offline_access', 'uma_authorization', 'default-roles-starter-app']
                    ]
                    user_info['roles'] = user_roles

            except Exception as e:
                # Log error but continue - roles are optional for basic authentication
                print(f"Warning: Could not extract roles from access token: {e}")

            # Create server-side session
            session_id = self.session_store.create_session(tokens, user_info)
            # Create redirect response
            redirect = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

            # Set httpOnly cookie on the redirect response
            redirect.set_cookie(
                key="session_id",
                value=session_id,
                httponly=True,
                secure=app_settings.environment == "production",
                samesite="lax",
                max_age=app_settings.session_timeout_hours * 3600,
                path="/"
            )

            return redirect

        except Exception as e:
            # Log error and redirect to login
            print(f"OAuth2 callback error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )

    @post("/refresh")
    async def refresh(self, session_id: Optional[str] = Cookie(None)):
        """Refresh session tokens using Keycloak refresh token.

        Returns new access/id tokens and updates the session store.
        """
        if not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing session cookie")
        session = self.session_store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
        refresh_token = session.get("tokens", {}).get("refresh_token")
        if not refresh_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No refresh token available")
        try:
            new_tokens = self.keycloak.refresh_token(refresh_token)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Refresh failed: {e}")

        if "refresh_token" not in new_tokens:
            new_tokens["refresh_token"] = refresh_token
        self.session_store.refresh_session(session_id, new_tokens)
        return {"access_token": new_tokens.get("access_token"), "id_token": new_tokens.get("id_token")}

    @get("/logout")
    async def logout(
        self,
        session_id: Optional[str] = Cookie(None)
    ):
        """Logout user - clear session and redirect to Keycloak logout.

        Args:
            session_id: Current session ID from cookie

        Returns:
            Redirect to Keycloak logout endpoint
        """
        id_token = None

        # Get id_token from session if available
        if session_id:
            session = self.session_store.get_session(session_id)
            if session:
                id_token = session.get('tokens', {}).get('id_token')
            # Delete server-side session
            self.session_store.delete_session(session_id)

        # Build Keycloak logout URL with post_logout_redirect_uri
        # Using post_logout_redirect_uri (not redirect_uri) for logout endpoint
        logout_url = (
            f"{app_settings.keycloak_url}/realms/{app_settings.keycloak_realm}"
            f"/protocol/openid-connect/logout?post_logout_redirect_uri={app_settings.app_url}/"
        )

        # Add id_token_hint if available for proper session termination
        if id_token:
            logout_url += f"&id_token_hint={id_token}"

        # Create redirect and clear cookie
        redirect = RedirectResponse(url=logout_url, status_code=status.HTTP_303_SEE_OTHER)
        redirect.delete_cookie("session_id", path="/")

        return redirect

    @get("/user")
    async def get_current_user(
        self,
        session_id: Optional[str] = Cookie(None)
    ):
        """Get current authenticated user information.

        Args:
            session_id: Session ID from cookie

        Returns:
            User information from Keycloak

        Raises:
            HTTPException: 401 if not authenticated or session expired
        """
        if not session_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated"
            )

        # Retrieve session
        session = self.session_store.get_session(session_id)

        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired"
            )

        # Return user info (never expose tokens to browser)
        return session['user_info']
