"""CozyLife local pull integration."""
from __future__ import annotations

import asyncio
from homeassistant.core import HomeAssistant
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.typing import ConfigType
import logging
from .const import (
    DOMAIN,
    LANG,
    TOKEN_CONF,
    DEVICE_KEYS_CONF,
)
from .utils import get_pid_list
from .udp_discover import get_ip
from .tcp_client import tcp_client


_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    config: {'lang': 'zh', 'ip': ['192.168.5.201', '192.168.5.202']}
    """
    ip = await hass.async_add_executor_job(get_ip)
    ip_from_config = config[DOMAIN].get('ip') if config[DOMAIN].get('ip') is not None else []
    ip += ip_from_config
    ip_list = []
    [ip_list.append(i) for i in ip if i not in ip_list]

    if 0 == len(ip_list):
        _LOGGER.info('discover nothing')
        return True

    _LOGGER.info('try connect ip_list: %s', ip_list)
    lang_from_config = (config[DOMAIN].get('lang') if config[DOMAIN].get('lang') is not None else LANG)
    await hass.async_add_executor_job(get_pid_list, lang_from_config)

    token = config[DOMAIN].get(TOKEN_CONF)
    device_keys = config[DOMAIN].get(DEVICE_KEYS_CONF) or {}

    hass.data[DOMAIN] = {
        'temperature': 24,
        'ip': ip_list,
        'tcp_client': [
            tcp_client(item, token=token, device_keys=device_keys)
            for item in ip_list
        ],
    }

    # Wait for TCP connections and device info to be retrieved
    await asyncio.sleep(3)

    await async_load_platform(hass, 'light', DOMAIN, {}, config)
    await async_load_platform(hass, 'switch', DOMAIN, {}, config)
    return True
