"""
Interfaces with Wink Cameras.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/alarm_control_panel.wink/
"""
import logging

import homeassistant.components.alarm_control_panel as alarm
from homeassistant.const import (STATE_UNKNOWN,
                                 STATE_ALARM_DISARMED,
                                 STATE_ALARM_ARMED_HOME,
                                 STATE_ALARM_ARMED_AWAY)
from homeassistant.components.wink import WinkDevice, DOMAIN

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['wink']

STATE_ALARM_PRIVACY = 'Private'


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Wink platform."""
    import pywink

    for camera in pywink.get_cameras():
        # get_cameras returns multiple device types.
        # Only add those that aren't sensors.
        try:
            camera.capability()
        except AttributeError:
            _id = camera.object_id() + camera.name()
            if _id not in hass.data[DOMAIN]['unique_ids']:
                add_devices([WinkCameraDevice(camera, hass)])


class WinkCameraDevice(WinkDevice, alarm.AlarmControlPanel):
    """Representation a Wink camera alarm."""

    def __init__(self, wink, hass):
        """Initialize the Wink alarm."""
        super().__init__(wink, hass)

    @property
    def state(self):
        """Return the state of the device."""
        wink_state = self.wink.state()
        if wink_state == "away":
            state = STATE_ALARM_ARMED_AWAY
        elif wink_state == "home":
            state = STATE_ALARM_DISARMED
        elif wink_state == "night":
            state = STATE_ALARM_ARMED_HOME
        else:
            state = STATE_UNKNOWN
        return state

    def alarm_disarm(self, code=None):
        """Send disarm command."""
        self.wink.set_mode("home")

    def alarm_arm_home(self, code=None):
        """Send arm home command."""
        self.wink.set_mode("night")

    def alarm_arm_away(self, code=None):
        """Send arm away command."""
        self.wink.set_mode("away")

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            'private': self.wink.private()
        }
