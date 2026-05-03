"""Platform for light integration."""
from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_FLASH,
    ATTR_HS_COLOR,
    ATTR_RGB_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from typing import Any
from .const import (
    DOMAIN,
    SWITCH_TYPE_CODE,
    LIGHT_TYPE_CODE,
    LIGHT_DPID,
    SWITCH,
    WORK_MODE,
    TEMP,
    BRIGHT,
    HUE,
    SAT,
)
from .tcp_client import tcp_client
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the light platform."""
    _LOGGER.info(f'async_setup_platform discovery_info={discovery_info}')

    if discovery_info is None:
        return

    lights = []
    for item in hass.data[DOMAIN]['tcp_client']:
        if LIGHT_TYPE_CODE == item.device_type_code:
            lights.append(CozyLifeLight(item))

    async_add_entities(lights, update_before_add=True)


class CozyLifeLight(LightEntity):
    _tcp_client = None

    def __init__(self, tcp_client: tcp_client) -> None:
        """Initialize the light."""
        _LOGGER.info('__init__')
        self._tcp_client = tcp_client
        self._unique_id = tcp_client.device_id
        self._name = tcp_client.device_model_name + ' ' + tcp_client.device_id[-4:]

        # Instance-level to avoid shared mutable class attribute bug
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS, ColorMode.ONOFF}
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_brightness = None
        self._attr_color_temp_kelvin = None
        self._attr_hs_color = None
        self._attr_is_on = False

        if 3 in tcp_client.dpid:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_supported_color_modes.add(ColorMode.COLOR_TEMP)

        if 5 in tcp_client.dpid or 6 in tcp_client.dpid:
            self._attr_color_mode = ColorMode.HS
            self._attr_supported_color_modes.add(ColorMode.HS)

        _LOGGER.info(f'{self._unique_id}: color_mode={self._attr_color_mode} '
                     f'supported={self._attr_supported_color_modes} dpid={tcp_client.dpid}')

    def _apply_state(self, state: dict) -> None:
        """Apply a state dict to cached attributes."""
        if not state or '1' not in state:
            return
        self._attr_is_on = 0 < state['1']

        if '4' in state:
            self._attr_brightness = int(state['4'] / 4)

        if '5' in state and '6' in state:
            self._attr_hs_color = (int(state['5']), int(state['6'] / 10))

        if '3' in state:
            # Device range: 0 = coolest (6500K), 1000 = warmest (2700K)
            self._attr_color_temp_kelvin = round(6500 - (state['3'] / 1000) * 3800)

    async def async_update(self) -> None:
        """Fetch latest state from device (called by HA polling)."""
        state = await self.hass.async_add_executor_job(self._tcp_client.query)
        _LOGGER.info(f'async_update state={state}')
        if not state:
            _LOGGER.info('async_update: empty state, keeping last known state')
            return
        self._apply_state(state)

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str | None:
        return self._unique_id

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._attr_is_on

    @property
    def brightness(self) -> int | None:
        return self._attr_brightness

    @property
    def color_temp_kelvin(self) -> int | None:
        return self._attr_color_temp_kelvin

    @property
    def hs_color(self) -> tuple[float, float] | None:
        return self._attr_hs_color

    @property
    def color_mode(self) -> ColorMode | None:
        return self._attr_color_mode

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        colortemp_kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        hs_color = kwargs.get(ATTR_HS_COLOR)
        _LOGGER.info(f'async_turn_on kwargs={kwargs}')

        payload = {'1': 255, '2': 0}

        if brightness is not None:
            payload['4'] = brightness * 4
            self._attr_brightness = brightness

        if hs_color is not None:
            payload['5'] = int(hs_color[0])
            payload['6'] = int(hs_color[1] * 10)
            self._attr_hs_color = hs_color

        if colortemp_kelvin is not None:
            # Device range: 0 = coolest (6500K), 1000 = warmest (2700K)
            payload['3'] = max(0, min(1000, round((6500 - colortemp_kelvin) / 3800 * 1000)))
            self._attr_color_temp_kelvin = colortemp_kelvin

        self._attr_is_on = True
        await self.hass.async_add_executor_job(self._tcp_client.control, payload)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        _LOGGER.info(f'async_turn_off kwargs={kwargs}')
        self._attr_is_on = False
        await self.hass.async_add_executor_job(self._tcp_client.control, {'1': 0})

