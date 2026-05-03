"""Platform for switch integration."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from typing import Any
from .const import (
    DOMAIN,
    SWITCH_TYPE_CODE,
)
import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Set up the switch platform."""
    _LOGGER.info('async_setup_platform')

    if discovery_info is None:
        return

    switches = []
    for item in hass.data[DOMAIN]['tcp_client']:
        if SWITCH_TYPE_CODE == item.device_type_code:
            switches.append(CozyLifeSwitch(item))

    async_add_entities(switches, update_before_add=True)


class CozyLifeSwitch(SwitchEntity):
    _tcp_client = None

    def __init__(self, tcp_client) -> None:
        """Initialize the switch."""
        _LOGGER.info('__init__')
        self._tcp_client = tcp_client
        self._unique_id = tcp_client.device_id
        self._name = tcp_client.device_model_name + ' ' + tcp_client.device_id[-4:]
        self._attr_is_on = False

    async def async_update(self) -> None:
        """Fetch latest state from device (called by HA polling)."""
        state = await self.hass.async_add_executor_job(self._tcp_client.query)
        _LOGGER.info(f'async_update state={state}')
        if not state or '1' not in state:
            _LOGGER.info('async_update: empty state, keeping last known state')
            return
        self._attr_is_on = 0 != state['1']

    @property
    def name(self) -> str:
        return self._name

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._attr_is_on

    @property
    def unique_id(self) -> str | None:
        return self._unique_id

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        _LOGGER.info(f'async_turn_on: {kwargs}')
        self._attr_is_on = True
        await self.hass.async_add_executor_job(self._tcp_client.control, {'1': 255})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        _LOGGER.info('async_turn_off')
        self._attr_is_on = False
        await self.hass.async_add_executor_job(self._tcp_client.control, {'1': 0})

