import asyncio
import logging
import aiohttp
from functools import wraps
from typing import Optional, Callable, Any
from .const import (
    ESY_API_BASE_URL,
    ESY_API_LOGIN_ENDPOINT,
    ESY_API_DEVICE_ENDPOINT,
    ESY_API_OBTAIN_ENDPOINT,
    ESY_API_MODE_ENDPOINT,
    ESY_SCHEDULES_ENDPOINT,
    ATTR_SCHEDULE_MODE
)
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class TokenExpiredError(Exception):
    """Raised when the access token has expired."""
    pass


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """Decorator that retries a function with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        backoff_factor: Multiplier for delay on each retry
        exceptions: Tuple of exceptions to catch and retry
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        _LOGGER.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                        delay *= backoff_factor
                    else:
                        _LOGGER.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
            
            raise last_exception
        
        return wrapper
    return decorator


class ESYSunhomeAPI:
    def __init__(self, username, password, device_id) -> None:
        """Initialize with user credentials."""
        self.username = username
        self.password = password
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        self.device_id = device_id
        self.name = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close_session(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _make_request_with_auth(
        self,
        method: str,
        url: str,
        retry_auth: bool = True,
        **kwargs
    ) -> tuple[int, dict]:
        """Make an authenticated API request with automatic token refresh.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request
            retry_auth: Whether to retry with new token on 401
            **kwargs: Additional arguments to pass to the request
            
        Returns:
            Tuple of (status_code, response_data)
        """
        # Ensure we have a valid token
        await self.get_bearer_token()
        
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"bearer {self.access_token}"
        
        session = await self._get_session()
        
        async with session.request(method, url, headers=headers, **kwargs) as response:
            status = response.status
            
            # Handle 401 Unauthorized - token may have expired
            if status == 401 and retry_auth:
                _LOGGER.warning("Received 401, attempting to refresh token and retry")
                
                # Try to refresh the token
                self.access_token = None  # Force token refresh
                await self.get_bearer_token()
                
                # Retry the request with new token
                headers["Authorization"] = f"bearer {self.access_token}"
                async with session.request(method, url, headers=headers, **kwargs) as retry_response:
                    status = retry_response.status
                    try:
                        data = await retry_response.json()
                    except:
                        data = await retry_response.text()
                    return status, data
            
            # Parse response
            try:
                data = await response.json()
            except:
                data = await response.text()
            
            return status, data

    async def get_bearer_token(self):
        """Fetch the bearer token using the provided credentials asynchronously."""
        # Check if the token has expired
        if self.is_token_expired():
            _LOGGER.info("Access token expired, refreshing token")
            if not await self.refresh_access_token():
                _LOGGER.warning("Failed to refresh access token. Re-authenticating")
                await self.authenticate()
        elif not self.access_token:
            # If no token is available, authenticate
            await self.authenticate()

        if self.device_id is None or self.device_id == "":
            await self.fetch_device()

    @retry_with_backoff(max_retries=2, initial_delay=1.0)
    async def authenticate(self):
        """Authenticate and retrieve the initial bearer token."""
        url = f"{ESY_API_BASE_URL}{ESY_API_LOGIN_ENDPOINT}"
        headers = {"Content-Type": "application/json"}
        login_data = {
            "password": self.password,
            "clientId": "",
            "requestType": 1,
            "loginType": "PASSWORD",
            "userType": 2,
            "userName": self.username,
        }

        session = await self._get_session()
        async with session.post(url, json=login_data, headers=headers) as response:
            if response.status == 200:
                data = await response.json()

                # Extract tokens and expiration time
                self.access_token = data["data"].get("access_token")
                self.refresh_token = data["data"].get("refresh_token")
                expires_in = data["data"].get("expires_in", 0)
                self.token_expiry = datetime.utcnow() + timedelta(
                    seconds=expires_in
                )

                _LOGGER.info("Successfully authenticated and retrieved access token")
                _LOGGER.debug(f"Token expires in {expires_in} seconds")
                
                if self.device_id is None or self.device_id == "":
                    await self.fetch_device()
            else:
                error_text = await response.text()
                _LOGGER.error(f"Authentication failed: {response.status} - {error_text}")
                raise AuthenticationError(
                    f"Failed to retrieve access token. Status code: {response.status}"
                )

    async def refresh_access_token(self) -> bool:
        """Use the refresh token to get a new access token."""
        if not self.refresh_token:
            _LOGGER.warning("No refresh token available, will re-authenticate")
            return False

        url = f"{ESY_API_BASE_URL}/token"  # Adjust URL if needed for the refresh endpoint
        headers = {"Content-Type": "application/json"}
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }

        try:
            session = await self._get_session()
            async with session.post(url, json=refresh_data, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    # Extract new tokens and expiration time
                    self.access_token = data["data"].get("access_token")
                    self.refresh_token = data["data"].get("refresh_token")
                    expires_in = data["data"].get("expires_in", 0)
                    self.token_expiry = datetime.utcnow() + timedelta(
                        seconds=expires_in
                    )

                    _LOGGER.info("Access token successfully refreshed")
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"Failed to refresh access token: {response.status} - {error_text}")
                    return False
        except Exception as e:
            _LOGGER.error(f"Exception while refreshing token: {e}")
            return False

    def is_token_expired(self) -> bool:
        """Check if the access token has expired."""
        if not self.token_expiry:
            return True
        # Add a 60 second buffer before actual expiry
        return datetime.utcnow() >= (self.token_expiry - timedelta(seconds=60))

    @retry_with_backoff(max_retries=2, initial_delay=1.0)
    async def fetch_device(self):
        """Fetch the device (inverter) ID associated with the user."""
        if not self.access_token:
            raise AuthenticationError("Access token is required to fetch device ID")

        url = f"{ESY_API_BASE_URL}{ESY_API_DEVICE_ENDPOINT}"
        
        status, data = await self._make_request_with_auth("GET", url)
        
        if status == 200:
            if isinstance(data, dict) and "data" in data:
                self.device_id = data["data"]["records"][0]["id"]
                _LOGGER.info(f"Device ID retrieved: {self.device_id}")
            else:
                raise Exception(f"Unexpected response format: {data}")
        else:
            raise Exception(
                f"Failed to fetch device ID. Status code: {status}, Response: {data}"
            )

    @retry_with_backoff(max_retries=2, initial_delay=2.0)
    async def request_update(self):
        """Call the /api/param/set/obtain endpoint and publish data to MQTT."""
        url = f"{ESY_API_BASE_URL}{ESY_API_OBTAIN_ENDPOINT}{self.device_id}"
        
        status, data = await self._make_request_with_auth("GET", url)
        
        if status == 200:
            _LOGGER.debug("Data update requested successfully")
        else:
            _LOGGER.warning(f"Data update request returned status {status}: {data}")
            raise Exception(
                f"Failed to request data update. Status code: {status}"
            )

    @retry_with_backoff(max_retries=3, initial_delay=2.0, backoff_factor=1.5)
    async def set_mode(self, mode: int):
        """Call the mode endpoint to set the operation mode.
        
        This method includes retry logic because mode changes can sometimes
        take time to process on the server side.
        
        Args:
            mode: The operating mode code to set
        """
        url = f"{ESY_API_BASE_URL}{ESY_API_MODE_ENDPOINT}"
        
        _LOGGER.info(f"Setting mode to {mode} for device {self.device_id}")
        
        payload = {
            ATTR_SCHEDULE_MODE: mode,
            "deviceId": self.device_id
        }
        
        status, data = await self._make_request_with_auth("POST", url, json=payload)
        
        if status == 200:
            _LOGGER.info(f"Mode successfully updated to {mode}")
            
            # Check if response indicates success
            if isinstance(data, dict):
                success = data.get("success", True)
                message = data.get("message", "")
                
                if not success:
                    _LOGGER.warning(f"API returned success=false: {message}")
                    raise Exception(f"Mode change failed: {message}")
        else:
            _LOGGER.error(f"Failed to set mode. Status: {status}, Response: {data}")
            raise Exception(
                f"Failed to set mode. Status code: {status}"
            )

    async def update_schedule(self, mode: int):
        """Call the schedule endpoint to fetch the current schedule, not yet implemented."""
        url = f"{ESY_API_BASE_URL}{ESY_SCHEDULES_ENDPOINT}{self.device_id}"
        
        try:
            status, data = await self._make_request_with_auth("GET", url)
            
            _LOGGER.debug(f"Schedule fetch status: {status}")
            
            if status == 200:
                _LOGGER.debug(f"Current schedule: {data}")
            else:
                _LOGGER.warning(f"Failed to fetch schedule: {status} - {data}")
        except Exception as e:
            _LOGGER.error(f"Error fetching schedule: {e}")
            # Don't raise - this is not critical functionality


# Test script to run locally
# if __name__ == "__main__":
#     username = "testuser@test.com"
#     password = "password"
#
#     try:
#         api = ESYSunhomeAPI(username, password, None)
#         api.fetch_all_data()  # Start fetching data every 15 seconds
#     except Exception as e:
#         print(f"Error: {e}")
