"""
OAuth2 authentication handler for YouTube Data API v3.

This module manages the OAuth2 flow for YouTube API access, including:
- Initial authentication and authorization
- Token storage and retrieval
- Automatic token refresh
- Authentication validation
"""

import logging
import os
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# YouTube Data API v3 scopes
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube",
]

# Authentication file paths
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "client_secrets.json"


def _load_stored_credentials():
    """Load OAuth credentials from Google's authorized-user JSON format."""
    if not os.path.exists(TOKEN_FILE):
        return None

    try:
        credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        logger.debug("Loaded existing credentials from %s", TOKEN_FILE)
        return credentials
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        logger.error("The stored token file is not valid authorized-user JSON: %s", exc)
        logger.error(
            "Legacy pickle tokens are no longer supported. Delete %s and run "
            "'python -m yt_sub_playlist.auth.oauth' to authenticate again.",
            TOKEN_FILE,
        )
        raise SystemExit(1) from exc


def _save_credentials(credentials) -> None:
    """Atomically persist OAuth credentials as private JSON."""
    token_path = Path(TOKEN_FILE)
    temporary_path = token_path.with_name(f".{token_path.name}.tmp")
    try:
        temporary_path.write_text(credentials.to_json(), encoding="utf-8")
        try:
            temporary_path.chmod(0o600)
        except OSError:
            logger.debug("Could not tighten permissions on %s", temporary_path)
        temporary_path.replace(token_path)
        logger.debug("Credentials saved to %s", TOKEN_FILE)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        logger.warning("Failed to save credentials: %s", exc)


def get_authenticated_service():
    """
    Authenticate and return a YouTube API service object.
    
    Handles the complete OAuth2 flow including:
    - Loading existing tokens
    - Refreshing expired tokens  
    - Running new authentication flow if needed
    - Saving tokens for future use

    Returns:
        googleapiclient.discovery.Resource: Authenticated YouTube API service

    Raises:
        SystemExit: If authentication fails completely
    """
    creds = _load_stored_credentials()

    # If there are no valid credentials, refresh or get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("Refreshing expired token...")
                creds.refresh(Request())
                logger.info("Token refreshed successfully")
            except RefreshError as e:
                logger.error(f"Token refresh failed: {e}")
                logger.info("Starting new authentication flow...")
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_FILE):
                logger.error(f"Credentials file {CREDENTIALS_FILE} not found")
                logger.error(
                    "Please download your OAuth2 credentials from Google Cloud Console"
                )
                logger.error("and save them as 'client_secrets.json'")
                raise SystemExit(1)

            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
                logger.info("Authentication completed successfully")
            except Exception as e:
                logger.error(f"Authentication failed: {e}")
                raise SystemExit(1)

        # Save the credentials for the next run
        _save_credentials(creds)

    try:
        service = build("youtube", "v3", credentials=creds)
        logger.debug("YouTube API service created successfully")
        return service
    except Exception as e:
        logger.error(f"Failed to build YouTube API service: {e}")
        raise SystemExit(1)


def test_authentication():
    """
    Test authentication by making a simple API call.
    
    Validates that the authentication flow works and the user
    has the necessary permissions for YouTube API access.
    
    Returns:
        bool: True if authentication test passes, False otherwise
    """
    try:
        service = get_authenticated_service()
        response = service.channels().list(part="snippet", mine=True).execute()

        if "items" in response and response["items"]:
            channel = response["items"][0]["snippet"]
            logger.info(f"Authentication successful for channel: {channel['title']}")
            return True
        else:
            logger.error("Authentication failed: No channel data returned")
            return False

    except SystemExit:
        return False
    except Exception as e:
        logger.error(f"Authentication test failed: {e}")
        return False


def reset_authentication():
    """
    Reset authentication by removing stored tokens.
    
    This forces a fresh authentication flow on the next API call.
    Useful when authentication issues occur or when switching accounts.
    """
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
            logger.info(f"Removed existing token file: {TOKEN_FILE}")
        else:
            logger.info("No existing token file found")
    except Exception as e:
        logger.error(f"Failed to remove token file: {e}")


if __name__ == "__main__":
    # Allow direct testing of authentication
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    print("Testing YouTube API authentication...")
    success = test_authentication()
    
    if success:
        print("✅ Authentication successful!")
    else:
        print("❌ Authentication failed")
        
    exit(0 if success else 1)
