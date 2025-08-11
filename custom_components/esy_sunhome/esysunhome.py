import logging
import aiohttp
from .const import (
    ESY_API_BASE_URL,
    ESY_API_LOGIN_ENDPOINT,
    ESY_API_DEVICE_ENDPOINT,
    ESY_API_OBTAIN_ENDPOINT,
    ESY_API_MODE_ENDPOINT,
    ATTR_SCHEDULE_MODE
)
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)


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

    async def get_bearer_token(self):
        """Fetch the bearer token using the provided credentials asynchronously."""
        # Check if the token has expired
        if self.is_token_expired():
            _LOGGER.info("Access token expired, refreshing token")
            if not await self.refresh_access_token():
                _LOGGER.error("Failed to refresh access token. Re-authenticating")
                await self.authenticate()
        elif not self.access_token:
            # If no token is available, authenticate
            await self.authenticate()

        if self.device_id is None or self.device_id == "":
            await self.fetch_device()

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

        async with aiohttp.ClientSession() as session:
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

                    _LOGGER.debug(f"Access token retrieved: {self.access_token}")
                    if self.device_id is None or self.device_id == "":
                        await self.fetch_device()
                else:
                    await session.close()
                    raise Exception(
                        f"Failed to retrieve access token. Status code: {response.status}"
                    )

        await session.close()

    async def refresh_access_token(self):
        """Use the refresh token to get a new access token."""
        if not self.refresh_token:
            _LOGGER.error("No refresh token available")
            return False

        url = f"{self.base_url}/token"  # Adjust URL if needed for the refresh endpoint
        headers = {"Content-Type": "application/json"}
        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }

        result = None

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=refresh_data, headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    # Extract new tokens and expiration time
                    self.access_token = data["data"].get("access_token")
                    self.refresh_token = data["data"].get("refresh_token")
                    expires_in = data["data"].get("expires_in", 0)
                    self.token_expiry = datetime.utcnow() + timedelta(
                        seconds=expires_in
                    )

                    _LOGGER.debug(f"Access token refreshed: {self.access_token}")
                    result = True
                else:
                    _LOGGER.error("Failed to refresh access token")
                    result = False

        await session.close()
        return result

    def is_token_expired(self):
        """Check if the access token has expired."""
        if not self.token_expiry:
            return True
        return datetime.utcnow() >= self.token_expiry

    async def fetch_device(self):
        """Fetch the device (inverter) ID associated with the user."""
        if not self.access_token:
            raise Exception("Access token is required to fetch device ID")

        url = f"{ESY_API_BASE_URL}{ESY_API_DEVICE_ENDPOINT}"
        headers = {"Authorization": f"bearer {self.access_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    self.device_id = data["data"]["records"][0]["id"]
                    _LOGGER.debug(f"Device ID retrieved: {self.device_id}")
                else:
                    raise Exception(
                        f"Failed to fetch device ID. Status code: {response.status}"
                    )

        await session.close()

    async def request_update(self):
        """Call the /api/param/set/obtain endpoint and publish data to MQTT."""
        await self.get_bearer_token()

        url = f"{ESY_API_BASE_URL}{ESY_API_OBTAIN_ENDPOINT}{self.device_id}"
        headers = {"Authorization": f"bearer {self.access_token}"}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    _LOGGER.debug("Data update requested")
                else:
                    raise Exception(
                        f"Failed to fetch data. Status code: {response.status}"
                    )

        await session.close()

    async def set_mode(self, mode: int):
        """Call the mode endpoint to set the operation mode."""
        await self.get_bearer_token()

        url = f"{ESY_API_BASE_URL}{ESY_API_MODE_ENDPOINT}"
        headers = {"Authorization": f"bearer {self.access_token}"}

        _LOGGER.info(f"Setting mode to {mode} for device {self.device_id}")

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={ATTR_SCHEDULE_MODE: mode, "deviceId": self.device_id}, headers=headers) as response:
                _LOGGER.debug(f"Response status: {response.status}, Response body: {await response.text()}")
                if response.status == 200:
                    _LOGGER.debug(f"Mode successfully updated to {mode}")
                else:
                    raise Exception(
                        f"Failed to set mode. Status code: {response.status}"
                    )

        await session.close()

# Test script to run locally
# if __name__ == "__main__":
#     username = "testuser@test.com"
#     password = "password"

#     try:
#         api = ESYSunhomeAPI(username, password, None)
#         api.fetch_all_data()  # Start fetching data every 15 seconds
#     except Exception as e:
#         print(f"Error: {e}")
