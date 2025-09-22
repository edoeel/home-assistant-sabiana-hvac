"""Climate platform for Sabiana HVAC integration."""
from __future__ import annotations

import logging
from typing import Any, Callable

import httpx
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_SLEEP,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import api
from .api import SabianaApiAuthError, SabianaApiClientError
from .const import (
    DOMAIN,
    CONF_TOKEN,
    HVAC_MODE_MAP,
    FAN_MODE_MAP,
    SWING_MODE_MAP,
    COMMAND_PART_11_19_FIXED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entities = [
        SabianaHvacClimateEntity(
            entry_data["session"], entry_data[CONF_TOKEN], device
        )
        for device in entry_data["devices"]
    ]
    async_add_entities(entities)


class SabianaHvacClimateEntity(ClimateEntity, RestoreEntity):

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY]
    _attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO]
    _attr_swing_modes = ["Vertical", "Horizontal", "45 Degrees", "Swing"]
    _attr_preset_modes = [PRESET_SLEEP]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 10.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 1 # TODO it could be 0.5
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, session: httpx.AsyncClient, token: str, device: api.SabianaDevice
    ) -> None:
        self._session = session
        self._token = token
        self._device = device
        self._attr_unique_id = device.id
        self._attr_name = device.name

        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 25.0
        self._attr_fan_mode = FAN_AUTO
        self._attr_swing_mode = "Swing"
        self._attr_preset_mode = None

    def _celsius_to_hex(self, temp: float) -> str:
        converted_value = int(temp * 10)
        return f"{converted_value:04x}"

    def _map_fan_mode_to_sabiana_char(self, fan_mode: str | None) -> str:
        return FAN_MODE_MAP.get(fan_mode, "4")

    def _map_hvac_mode_to_sabiana_char(self, hvac_mode: HVACMode | None) -> str:
        return HVAC_MODE_MAP.get(hvac_mode, "4")

    def _map_swing_mode_to_sabiana_char(self, swing_mode: str | None) -> str:
        return SWING_MODE_MAP.get(swing_mode, "4")

    def _map_preset_mode_to_sabiana_char(self, preset_mode: str | None) -> str:
        return "2" if preset_mode == PRESET_SLEEP else "0"

    def _build_command_payload(self) -> str:
        char1 = "0"
        char2 = self._map_fan_mode_to_sabiana_char(self.fan_mode)
        char3 = "0"
        char4 = self._map_hvac_mode_to_sabiana_char(self.hvac_mode)
        chars5_8 = self._celsius_to_hex(self.target_temperature)
        char9 = "0"
        char10 = self._map_swing_mode_to_sabiana_char(self.swing_mode)
        chars11_19 = COMMAND_PART_11_19_FIXED
        char20 = self._map_preset_mode_to_sabiana_char(self.preset_mode)

        return f"{char1}{char2}{char3}{char4}{chars5_8}{char9}{char10}{chars11_19}{char20}"


    async def _async_execute_command(self) -> None:
        command_payload = self._build_command_payload()
        try:
            await api.async_send_command(
                self._session, self._token, self._device.id, command_payload
            )
            self.async_write_ha_state()
        except SabianaApiAuthError as err:
            _LOGGER.error(
                "Authentication error for %s: %s. Please re-configure the integration.",
                self.name, err
            )
        except SabianaApiClientError as err:
            _LOGGER.error(
                "API error while sending command to %s: %s", self.name, err
            )
        except httpx.RequestError as err:
            _LOGGER.error(
                "Connection error while sending command to %s: %s",
                self.name, err
            )
        except Exception as err:
            _LOGGER.exception("Unexpected error while sending command to %s", self.name)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if last_state := await self.async_get_last_state():
            self._attr_hvac_mode = last_state.state
            self._attr_target_temperature = last_state.attributes.get(ATTR_TEMPERATURE)
            self._attr_fan_mode = last_state.attributes.get("fan_mode")
            self._attr_swing_mode = last_state.attributes.get("swing_mode")
            self._attr_preset_mode = last_state.attributes.get("preset_mode")
            _LOGGER.debug("Restored state for %s", self.name)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._attr_hvac_mode = hvac_mode
        await self._async_execute_command()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = temp
            await self._async_execute_command()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self._attr_fan_mode = fan_mode
        await self._async_execute_command()
        
    async def async_set_swing_mode(self, swing_mode: str) -> None:
        self._attr_swing_mode = swing_mode
        await self._async_execute_command()

    async def async_set_preset_mode(self, preset_mode: str | None) -> None:
        self._attr_preset_mode = preset_mode
        await self._async_execute_command()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
