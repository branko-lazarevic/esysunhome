import asyncio
import logging
import aiohttp
import ssl
import tempfile
import os
from functools import wraps
from typing import Optional, Callable, Any, Dict
from dataclasses import dataclass
from .const import (
    ESY_API_BASE_URL,
    ESY_API_LOGIN_ENDPOINT,
    ESY_API_DEVICE_ENDPOINT,
    ESY_API_OBTAIN_ENDPOINT,
    ESY_API_MODE_ENDPOINT,
    ESY_SCHEDULES_ENDPOINT,
    ESY_API_DEVICE_INFO,
    ESY_API_CERT_ENDPOINT,
    ATTR_SCHEDULE_MODE
)
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)


@dataclass
class MqttCredentials:
    """Container for MQTT connection credentials and certificates."""
    broker_url: str
    port: int
    username: str
    password: str
    ca_cert_path: Optional[str] = None
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None
    use_tls: bool = True


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
        """Fetch the bearer token using the provided credentials asynchronously.
        
        This method ONLY handles token management. Device fetching is separate.
        """
        # Check if the token has expired
        if self.is_token_expired():
            _LOGGER.info("Access token expired, refreshing token")
            if not await self.refresh_access_token():
                _LOGGER.warning("Failed to refresh access token. Re-authenticating")
                await self.authenticate()
        elif not self.access_token:
            # If no token is available, authenticate
            await self.authenticate()

    async def ensure_device_id(self):
        """Ensure we have a device ID, fetching if necessary.
        
        Call this AFTER get_bearer_token() when device_id is needed.
        """
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
        await self.ensure_device_id()
        
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
        await self.ensure_device_id()
        
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
        await self.ensure_device_id()
        
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

    @retry_with_backoff(max_retries=2, initial_delay=1.0)
    async def get_device_info(self) -> Dict[str, Any]:
        """Fetch detailed device info including MQTT credentials.
        
        Returns:
            Device info dict with mqttUserName, mqttPassword, sn, etc.
        """
        await self.ensure_device_id()
        
        url = f"{ESY_API_BASE_URL}{ESY_API_DEVICE_INFO}?id={self.device_id}"
        
        status, data = await self._make_request_with_auth("GET", url)
        
        if status == 200 and isinstance(data, dict) and data.get("code") == 0:
            device_info = data.get("data", {})
            _LOGGER.info(f"Retrieved device info for {device_info.get('sn', 'unknown')}")
            return device_info
        else:
            raise Exception(f"Failed to fetch device info. Status: {status}, Response: {data}")

    @retry_with_backoff(max_retries=2, initial_delay=1.0)
    async def get_mqtt_certs(self) -> Dict[str, Any]:
        """Fetch MQTT certificate URLs from the API.
        
        Returns:
            Dict with mqttDomain, port, ca, clientCrt, clientKey URLs
        """
        url = f"{ESY_API_BASE_URL}{ESY_API_CERT_ENDPOINT}"
        
        status, data = await self._make_request_with_auth("GET", url)
        
        if status == 200 and isinstance(data, dict) and data.get("code") == 0:
            cert_info = data.get("data", {})
            _LOGGER.info(f"Retrieved MQTT cert info: domain={cert_info.get('mqttDomain')}, port={cert_info.get('port')}")
            return cert_info
        else:
            raise Exception(f"Failed to fetch MQTT certs. Status: {status}, Response: {data}")

    async def download_file(self, url: str, dest_path: str) -> bool:
        """Download a file from URL to local path.
        
        Args:
            url: URL to download from (e.g., S3 presigned URL)
            dest_path: Local file path to save to
            
        Returns:
            True if successful
        """
        import asyncio
        
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.read()
                    
                    # Write file in executor to avoid blocking
                    def write_file():
                        with open(dest_path, 'wb') as f:
                            f.write(content)
                    
                    await asyncio.get_event_loop().run_in_executor(None, write_file)
                    _LOGGER.debug(f"Downloaded {len(content)} bytes to {dest_path}")
                    return True
                else:
                    _LOGGER.error(f"Failed to download {url}: {response.status}")
                    return False
        except Exception as e:
            _LOGGER.error(f"Error downloading {url}: {e}")
            return False

    async def get_mqtt_credentials(self, cert_dir: str) -> MqttCredentials:
        """Get complete MQTT credentials including downloaded certificates.
        
        This method:
        1. Fetches device info for username/password
        2. Fetches certificate URLs
        3. Downloads certificates to cert_dir
        4. Returns MqttCredentials with all info needed to connect
        
        Args:
            cert_dir: Directory to store downloaded certificates
            
        Returns:
            MqttCredentials object with all connection info
        """
        from .const import ESY_MQTT_BROKER_URL, ESY_MQTT_BROKER_PORT, ESY_MQTT_USERNAME, ESY_MQTT_PASSWORD
        
        # Create cert directory if needed
        os.makedirs(cert_dir, exist_ok=True)
        
        # Get device info for MQTT username/password
        try:
            device_info = await self.get_device_info()
            mqtt_username = device_info.get("mqttUserName", ESY_MQTT_USERNAME)
            mqtt_password = device_info.get("mqttPassword", ESY_MQTT_PASSWORD)
            _LOGGER.info(f"Using MQTT credentials from device info: username={mqtt_username}")
        except Exception as e:
            _LOGGER.warning(f"Failed to get device info, using fallback credentials: {e}")
            mqtt_username = ESY_MQTT_USERNAME
            mqtt_password = ESY_MQTT_PASSWORD
        
        # Get certificate URLs
        try:
            cert_info = await self.get_mqtt_certs()
            broker_url = cert_info.get("mqttDomain", ESY_MQTT_BROKER_URL)
            broker_port = cert_info.get("port", ESY_MQTT_BROKER_PORT)
            
            # Certificate file paths
            ca_path = os.path.join(cert_dir, "root.crt")
            client_cert_path = os.path.join(cert_dir, "client.crt")
            client_key_path = os.path.join(cert_dir, "client.key")
            
            # Download certificates
            ca_url = cert_info.get("ca")
            client_crt_url = cert_info.get("clientCrt")
            client_key_url = cert_info.get("clientKey")
            
            certs_downloaded = True
            
            if ca_url:
                if not await self.download_file(ca_url, ca_path):
                    certs_downloaded = False
                    _LOGGER.warning("Failed to download CA certificate")
            
            if client_crt_url:
                if not await self.download_file(client_crt_url, client_cert_path):
                    certs_downloaded = False
                    _LOGGER.warning("Failed to download client certificate")
            
            if client_key_url:
                if not await self.download_file(client_key_url, client_key_path):
                    certs_downloaded = False
                    _LOGGER.warning("Failed to download client key")
            
            if certs_downloaded and os.path.exists(ca_path) and os.path.exists(client_cert_path) and os.path.exists(client_key_path):
                _LOGGER.info("All certificates downloaded successfully, using mTLS")
                return MqttCredentials(
                    broker_url=broker_url,
                    port=broker_port,
                    username=mqtt_username,
                    password=mqtt_password,
                    ca_cert_path=ca_path,
                    client_cert_path=client_cert_path,
                    client_key_path=client_key_path,
                    use_tls=True
                )
            else:
                _LOGGER.warning("Certificate download incomplete, falling back to basic TLS")
                return MqttCredentials(
                    broker_url=broker_url,
                    port=broker_port,
                    username=mqtt_username,
                    password=mqtt_password,
                    use_tls=True
                )
                
        except Exception as e:
            _LOGGER.warning(f"Failed to get certificates, using fallback connection: {e}")
            return MqttCredentials(
                broker_url=ESY_MQTT_BROKER_URL,
                port=ESY_MQTT_BROKER_PORT,
                username=mqtt_username,
                password=mqtt_password,
                use_tls=False  # Fall back to non-TLS
            )
# if __name__ == "__main__":
#     username = "testuser@test.com"
#     password = "password"
#
#     try:
#         api = ESYSunhomeAPI(username, password, None)
#         api.fetch_all_data()  # Start fetching data every 15 seconds
#     except Exception as e:
#         print(f"Error: {e}")
