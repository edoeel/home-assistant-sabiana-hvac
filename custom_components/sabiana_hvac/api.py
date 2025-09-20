import httpx
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from .const import BASE_URL, USER_AGENT

_LOGGER = logging.getLogger(__name__)

class SabianaApiClientError(Exception):
    pass

class SabianaApiAuthError(SabianaApiClientError):
    pass

@dataclass(frozen=True)
class SabianaDevice:
    id: str
    name: str

def create_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "Host": "be-standard.sabianawm.cloud",
        "content-type": "application/json",
        "accept": "application/json, text/plain, */*",
        "sec-fetch-site": "cross-site",
        "accept-language": "it-IT,it;q=0.9",
        "sec-fetch-mode": "cors",
        "origin": "capacitor://sabianawm.cloud",
        "user-agent": USER_AGENT,
        "sec-fetch-dest": "empty",
    }
    if token:
        headers["auth"] = token
    return headers

def is_http_error(status: int) -> bool:
    return status >= 400

def is_auth_error(status: int) -> bool:
    return status == 401

def is_api_error(data: Dict[str, Any]) -> bool:
    return data.get("status", 0) != 0

def is_auth_api_error(data: Dict[str, Any]) -> bool:
    return data.get("status", 0) in [99, 103]

def validate_response(response: httpx.Response) -> Dict[str, Any]:
    _validate_http_status(response)
    data = response.json()
    _validate_api_status(data)
    return data

def _validate_http_status(response: httpx.Response) -> None:
    if not is_http_error(response.status_code):
        return
    
    if is_auth_error(response.status_code):
        raise SabianaApiAuthError("Authentication error")
    
    raise SabianaApiClientError(f"Request failed: {response.status_code}")

def _validate_api_status(data: Dict[str, Any]) -> None:
    if not is_api_error(data):
        return
    
    error_message = data.get("errorMessage", "Unknown API error")
    
    if is_auth_api_error(data):
        raise SabianaApiAuthError(error_message)
    
    raise SabianaApiClientError(error_message)

def extract_token(data: Dict[str, Any]) -> str:
    return data["body"]["user"]["token"]

def extract_devices(data: Dict[str, Any]) -> List[SabianaDevice]:
    devices_data = data.get("body", {}).get("devices", [])
    return [SabianaDevice(id=d["idDevice"], name=d["deviceName"]) for d in devices_data]

def extract_result(data: Dict[str, Any]) -> bool:
    return data.get("body", {}).get("result", False)

async def async_authenticate(session: httpx.AsyncClient, email: str, password: str) -> str:
    url = f"{BASE_URL}/users/login"
    payload = {"email": email, "password": password}
    headers = create_headers()
    
    _LOGGER.debug("Authenticating with Sabiana API")
    response = await session.post(url, headers=headers, json=payload)
    data = validate_response(response)
    token = extract_token(data)
    _LOGGER.debug("Successfully authenticated with Sabiana API")
    return token

async def async_get_devices(session: httpx.AsyncClient, token: str) -> List[SabianaDevice]:
    url = f"{BASE_URL}/devices/getDeviceForUserV2"
    headers = create_headers(token)
    
    _LOGGER.debug("Fetching devices from Sabiana API")
    response = await session.get(url, headers=headers)
    data = validate_response(response)
    devices = extract_devices(data)
    _LOGGER.debug("Retrieved %d devices from Sabiana API", len(devices))
    return devices

async def async_send_command(session: httpx.AsyncClient, token: str, device_id: str, data: str) -> bool:
    url = f"{BASE_URL}/devices/cmd"
    headers = create_headers(token)
    payload = {"deviceID": device_id, "start": 2304, "data": data, "restart": False}
    
    _LOGGER.debug("Sending command to device %s: %s", device_id, data)
    response = await session.post(url, headers=headers, json=payload)
    response_data = validate_response(response)
    result = extract_result(response_data)
    _LOGGER.debug("Command result for device %s: %s", device_id, result)
    return result
