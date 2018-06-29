"""
Support for OhmConnect.

For more details about this platform, please refer to the documentation
https://home-assistant.io/components/sensor.ohmconnect/
"""
import logging
from datetime import timedelta
import xml.etree.ElementTree as ET
import time

import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv
from homeassistant.util import Throttle
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

CONF_ID = 'id'

DEFAULT_NAME = 'OhmConnect Status'

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=1)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_ID): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the OhmConnect sensor."""
    name = config.get(CONF_NAME)
    ohmid = config.get(CONF_ID)

    add_devices([OhmconnectSensor(name, ohmid)], True)


class OhmconnectSensor(Entity):
    """Representation of a OhmConnect sensor."""

    def __init__(self, name, ohmid):
        """Initialize the sensor."""
        self._name = name
        self._ohmid = ohmid
        self._data = {}

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        if self._data.get("active") == "True":
            return "Active"
        return "Inactive"

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {"Address": self._data.get("address"), "ID": self._ohmid}

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Get the latest data from OhmConnect."""
        for attempt in range(3):
            try:
                url = ("https://login.ohmconnect.com"
                       "/verify-ohm-hour/{}").format(self._ohmid)
                response = requests.get(url, timeout=10)
                root = ET.fromstring(response.text)

                for child in root:
                    self._data[child.tag] = child.text
            except requests.exceptions.ConnectionError:
                err_msg = "No route to host/endpoint: " + str(url)
                self.data = {}
            except ET.ParseError as parse_err:
                err_msg = "XML parse error: " + str(parse_err)
                self.data = {}
            else:
                break
            time.sleep(1)
        else:
            _LOGGER.error("Failure, exceeded number of update attempts...\n%s", err_msg)
