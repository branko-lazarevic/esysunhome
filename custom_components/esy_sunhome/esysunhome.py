from custom_components.esy_sunhome.battery import EsySunhomeBattery
import requests

from .constants import BASE_URL, API_LOGIN_ENDPOINT, API_DEVICE_ENDPOINT, API_OBTAIN_ENDPOINT

class ESYSunhomeAPI:
    def __init__(self, username, password, device_id):
        """Initialize with user credentials, MQTT broker details, and subscribe to MQTT topics."""
        self.username = username
        self.password = password
        self.access_token = None
        self.device_id = device_id
        self.name = None
        self.get_bearer_token()
        
        if (device_id is None or device_id == ""):
            self.fetch_device()
            
        self.battery = EsySunhomeBattery(self.device_id)

    def get_bearer_token(self):
        """Fetch the bearer token using the provided credentials."""
        url = f"{BASE_URL}{API_LOGIN_ENDPOINT}"
        headers = {"Content-Type": "application/json"}
        login_data = {
            "password": self.password,
            "clientId": "",
            "requestType": 1,
            "loginType": "PASSWORD",
            "userType": 2,
            "userName": self.username,
        }
        
        response = requests.post(url, json=login_data, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            self.access_token = data['data']["access_token"]
        else:
            raise Exception("Failed to retrieve access token. Check your credentials.")

    def fetch_device(self):
        """Fetch the device (inverter) ID associated with the user."""
        if not self.access_token:
            raise Exception("Access token is required to fetch device ID.")

        url = f"{BASE_URL}{API_DEVICE_ENDPOINT}"
        headers = {"Authorization": f"bearer {self.access_token}"}
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            self.device_id = data['data']['records'][0]['id']
            self.name = data['data']['records'][0]['name']
            print(f"Device ID retrieved: {self.device_id}")
        else:
            raise Exception("Failed to fetch device ID.")

    def request_update(self):
        """Call the /api/param/set/obtain endpoint and publish data to MQTT."""
        if not self.device_id or not self.access_token:
            print("Device ID or access token not available.")
            return

        url = f"{BASE_URL}{API_OBTAIN_ENDPOINT}{self.device_id}"
        headers = {"Authorization": f"bearer {self.access_token}"}
        
        response = requests.get(url, headers=headers)
        
        if (response.status_code != 200):
            print("Failed to fetch data from /api/param/set/obtain.")

# Test script to run locally
# if __name__ == "__main__":    
#     username = "testuser@test.com"
#     password = "password"

#     try:
#         api = ESYSunhomeAPI(username, password, None)
#         api.fetch_all_data()  # Start fetching data every 15 seconds
#     except Exception as e:
#         print(f"Error: {e}")