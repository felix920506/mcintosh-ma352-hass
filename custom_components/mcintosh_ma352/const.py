"""Constants for the McIntosh MA352 integration."""

from typing import Final

DOMAIN: Final = "mcintosh_ma352"
MANUFACTURER: Final = "McIntosh"
MODEL: Final = "MA352"

CONF_SERIAL_PORT: Final = "serial_port"
CONF_BAUDRATE: Final = "baudrate"
CONF_MAX_VOLUME: Final = "max_volume"

DEFAULT_MAX_VOLUME: Final = 100

# Full status poll; also acts as a keepalive for network serial servers.
POLL_INTERVAL: Final = 60
RECONNECT_INTERVAL: Final = 10
# Time the amplifier needs after power-on before it reports complete status.
POWER_ON_REFRESH_DELAY: Final = 3
