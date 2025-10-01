
import requests
import time
import json

class MeaterAPI:
    """
    MEATER Cloud REST API client for temperature data collection
    """

    def __init__(self):
        """Initialize MEATER API client"""
        self.base_url = "https://public-api.cloud.meater.com/v1"
        self.token = None
        self.rate_limit_delay = 30  # seconds between requests (recommended: 2 req/60s)

    def authenticate(self, email, password):
        """
        Authenticate with MEATER Cloud API

        Parameters:
        email: MEATER account email
        password: MEATER account password

        Returns:
        bool: True if authentication successful
        """
        login_url = f"{self.base_url}/login"

        login_data = {
            "email": email,
            "password": password
        }

        headers = {
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(login_url, json=login_data, headers=headers)

            if response.status_code == 200:
                data = response.json()
                self.token = data['data']['token']
                print("Authentication successful!")
                return True
            else:
                print(f"Authentication failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            print(f"Authentication error: {e}")
            return False

    def get_devices(self):
        """
        Get all connected MEATER devices

        Returns:
        dict: Device information or None if error
        """
        if not self.token:
            print("Not authenticated. Please call authenticate() first.")
            return None

        devices_url = f"{self.base_url}/devices"

        headers = {
            "Authorization": f"Bearer {self.token}"
        }

        try:
            response = requests.get(devices_url, headers=headers)

            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to get devices: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            print(f"Error getting devices: {e}")
            return None

    def get_device(self, device_id):
        """
        Get specific device information and current temperature readings

        Parameters:
        device_id: ID of the MEATER device

        Returns:
        dict: Device information or None if error
        """
        if not self.token:
            print("Not authenticated. Please call authenticate() first.")
            return None

        device_url = f"{self.base_url}/devices/{device_id}"

        headers = {
            "Authorization": f"Bearer {self.token}"
        }

        try:
            response = requests.get(device_url, headers=headers)

            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to get device {device_id}: {response.status_code}")
                return None

        except Exception as e:
            print(f"Error getting device: {e}")
            return None

    def collect_temperature_data(self, device_id=None, duration_hours=2, interval_minutes=1):
        """
        Collect temperature data over time from MEATER device

        Parameters:
        device_id: ID of specific device (if None, uses first available)
        duration_hours: How long to collect data (hours)
        interval_minutes: How often to collect data (minutes)

        Returns:
        dict: Time series temperature data
        """
        if not self.token:
            print("Not authenticated. Please call authenticate() first.")
            return None

        # If no device_id specified, get first available device
        if device_id is None:
            devices = self.get_devices()
            if not devices or not devices['data']['devices']:
                print("No devices available")
                return None
            device_id = devices['data']['devices'][0]['id']
            print(f"Using device: {device_id}")

        print(f"Collecting temperature data from device {device_id}")
        print(f"Duration: {duration_hours} hours, Interval: {interval_minutes} minutes")
        print("Data collection started...")

        time_data = []
        internal_temp_data = []
        ambient_temp_data = []

        start_time = time.time()
        end_time = start_time + (duration_hours * 3600)
        interval_seconds = interval_minutes * 60

        while time.time() < end_time:
            device_data = self.get_device(device_id)

            if device_data and 'data' in device_data:
                device_info = device_data['data']

                if 'temperature' in device_info:
                    current_time = (time.time() - start_time) / 3600  # Hours since start

                    internal_temp = device_info['temperature']['internal']
                    ambient_temp = device_info['temperature']['ambient']

                    time_data.append(current_time)
                    internal_temp_data.append(internal_temp)
                    ambient_temp_data.append(ambient_temp)

                    print(f"Time: {current_time:.2f}h, Internal: {internal_temp}°C, Ambient: {ambient_temp}°C")
                else:
                    print("No temperature data available from device")
            else:
                print("Failed to get device data")

            # Wait for next interval (respect rate limits)
            wait_time = max(interval_seconds, self.rate_limit_delay)
            time.sleep(wait_time)

        print("Data collection completed!")

        return {
            'time_hours': np.array(time_data),
            'internal_temperature': np.array(internal_temp_data),
            'ambient_temperature': np.array(ambient_temp_data),
            'device_id': device_id
        }
