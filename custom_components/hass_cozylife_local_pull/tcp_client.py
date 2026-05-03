# -*- coding: utf-8 -*-
import json
import socket
import time
from typing import Union, Any
import logging
from .utils import get_pid_list, get_sn
from .const import RELAY_HOST, RELAY_PORT
import threading

CMD_INFO = 0
CMD_QUERY = 2
CMD_SET = 3
_LOGGER = logging.getLogger(__name__)


def _parse_relay_line(line: str) -> dict:
    """Parse a relay protocol line.

    Relay lines look like:
      cmd=publish&device_id=xxx&topic=yyy&message={json with & and = inside}

    The 'message' field is always last and may contain & and = inside the JSON,
    so we split on '&message=' to isolate it before splitting the rest on '&'.
    """
    result = {}
    msg_marker = '&message='
    msg_idx = line.find(msg_marker)
    if msg_idx != -1:
        result['message'] = line[msg_idx + len(msg_marker):]
        line = line[:msg_idx]
    for part in line.split('&'):
        if '=' in part:
            k, _, v = part.partition('=')
            result[k] = v
    return result


class tcp_client(object):
    """Manages communication with a CozyLife device via the cloud relay server.

    Device info (pid, model, dpid list, type code) is fetched via UDP port 6095
    which responds freely.  Control and state query are done through the cloud
    relay at RELAY_HOST:RELAY_PORT using a simple text pub/sub protocol.

    Configuration requires:
      - token: account auth token (cmd=auth)
      - device_keys: dict of {device_id: device_key} (cmd=publish auth)

    Protocol summary:
      Send:  cmd=publish&device_id=DID&topic=control_DID&device_key=KEY&message={json}\r\n
      Recv:  cmd=publish&device_id=DID&topic=device_DID&message={json}\r\n
    """

    def __init__(self, ip, token=None, device_keys=None, device_id=None):
        self._ip = ip
        self._udp_port = 6095
        self._token = token
        self._device_keys = device_keys or {}

        self._connect = None
        self._device_key = None
        self._device_id = device_id  # May be pre-set from config
        self._pid = None
        self._device_type_code = None
        self._icon = None
        self._device_model_name = None
        self._dpid = []
        self._recv_buf = b''
        self._lock = threading.Lock()

        # Get device info (UDP first, relay fallback if UDP is blocked)
        self._device_info()

        # Resolve device_key now that _device_id is known
        if self._device_id and self._device_id in self._device_keys:
            self._device_key = self._device_keys[self._device_id]
            _LOGGER.info('Device key resolved for %s', self._device_id)
        else:
            _LOGGER.warning(
                'No device_key configured for device %s (ip=%s). '
                'Add it under device_keys in configuration.yaml.',
                self._device_id, self._ip,
            )

        # Connect to cloud relay
        self._reconnect()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _close_connection(self):
        if self._connect:
            try:
                self._connect.close()
            except Exception as e:
                _LOGGER.error('Error closing relay connection: %s', e)
            self._connect = None

    def _reconnect(self):
        """Start a background thread that connects (and re-connects) to the relay."""
        def reconnect_thread():
            while True:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(10)
                    s.connect((RELAY_HOST, RELAY_PORT))

                    if self._token:
                        s.sendall(
                            ('cmd=auth&token=' + self._token + '\r\n').encode()
                        )
                        time.sleep(0.3)

                    if self._device_id and self._device_key:
                        sub = (
                            'cmd=subscribe'
                            '&topic=device_' + self._device_id +
                            '&from=control'
                            '&device_id=' + self._device_id +
                            '&device_key=' + self._device_key + '\r\n'
                        )
                        s.sendall(sub.encode())
                        time.sleep(0.3)

                    self._connect = s
                    self._recv_buf = b''
                    _LOGGER.info('Relay connected for device %s', self._device_id)
                    return

                except Exception as e:
                    _LOGGER.info('Relay reconnect failed: %s', e)
                    time.sleep(60)

        thread = threading.Thread(target=reconnect_thread)
        thread.daemon = True
        thread.start()

    def _lookup_pid_list(self) -> None:
        """Populate type_code, icon, model_name, dpid from the cloud PID list."""
        pid_list = get_pid_list()
        for item in pid_list:
            for item1 in item.get('m', []):
                if item1.get('pid') == self._pid:
                    self._icon = item1.get('i')
                    self._device_model_name = item1.get('n')
                    self._dpid = item1.get('dpid', [])
                    self._device_type_code = item.get('c')
                    break
            if self._device_type_code:
                break
        _LOGGER.info(
            'Device info: id=%s pid=%s type=%s model=%s',
            self._device_id, self._pid,
            self._device_type_code, self._device_model_name,
        )

    def _device_info_via_relay(self, device_id: str, device_key: str) -> bool:
        """Fetch device info via relay CMD_INFO.  Returns True on success."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((RELAY_HOST, RELAY_PORT))
            if self._token:
                s.sendall(('cmd=auth&token=' + self._token + '\r\n').encode())
                time.sleep(0.3)
            sub = (
                'cmd=subscribe'
                '&topic=device_' + device_id +
                '&from=control'
                '&device_id=' + device_id +
                '&device_key=' + device_key + '\r\n'
            )
            s.sendall(sub.encode())
            time.sleep(0.3)
            sn = get_sn()
            msg = json.dumps(
                {'cmd': CMD_INFO, 'pv': 0, 'sn': sn, 'msg': {'attr': [0]}},
                separators=(',', ':'),
            )
            line = (
                'cmd=publish'
                '&device_id=' + device_id +
                '&topic=control_' + device_id +
                '&device_key=' + device_key +
                '&message=' + msg + '\r\n'
            )
            s.sendall(line.encode())
            buf = b''
            deadline = time.time() + 5
            found = False
            while time.time() < deadline and not found:
                s.settimeout(max(0.1, deadline - time.time()))
                try:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                except socket.timeout:
                    pass
                while b'\r\n' in buf:
                    raw_line, buf = buf.split(b'\r\n', 1)
                    parts = _parse_relay_line(raw_line.decode('utf-8', errors='replace'))
                    if (
                        parts.get('cmd') == 'publish'
                        and parts.get('topic') == 'device_' + device_id
                        and 'message' in parts
                    ):
                        try:
                            msg_obj = json.loads(parts['message'])
                            if msg_obj.get('sn') == sn:
                                msg_data = msg_obj.get('msg', {})
                                self._device_id = device_id
                                self._pid = msg_data.get('pid')
                                if self._pid:
                                    self._lookup_pid_list()
                                found = True
                                break
                        except (json.JSONDecodeError, AttributeError):
                            pass
            s.close()
            return found
        except Exception as e:
            _LOGGER.info('_device_info_via_relay failed: %s', e)
            return False

    def _device_info(self) -> None:
        """Fetch device info, trying UDP first, then relay as fallback.

        UDP CMD_INFO (port 6095) works when the device is on a reachable subnet.
        If UDP is blocked (e.g. HA Core container on a different subnet), we
        fall back to CMD_INFO via the cloud relay using pre-configured device_keys.
        """
        # --- Try UDP ---
        udp_ok = False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(3)
            sn = get_sn()
            msg = json.dumps(
                {'cmd': CMD_INFO, 'pv': 0, 'sn': sn, 'msg': {}},
                separators=(',', ':'),
            )
            s.sendto(msg.encode(), (self._ip, self._udp_port))
            data, _ = s.recvfrom(1024)
            s.close()
            resp = json.loads(data.strip())
            msg_data = resp.get('msg')
            if isinstance(msg_data, dict):
                self._device_id = msg_data.get('did')
                self._pid = msg_data.get('pid')
                if self._device_id and self._pid:
                    self._lookup_pid_list()
                    udp_ok = True
        except Exception as e:
            _LOGGER.info('_device_info UDP failed for %s: %s', self._ip, e)

        if udp_ok:
            return

        # --- Relay fallback ---
        # If device_id was pre-configured (passed in __init__), use it directly.
        # Otherwise try all device_keys until one succeeds.
        candidates = []
        if self._device_id and self._device_id in self._device_keys:
            candidates = [(self._device_id, self._device_keys[self._device_id])]
        elif self._device_keys:
            candidates = list(self._device_keys.items())

        if not candidates:
            _LOGGER.warning(
                'UDP failed and no device_keys configured for %s — device will be unavailable.',
                self._ip,
            )
            return

        for did, dkey in candidates:
            _LOGGER.info('Trying relay CMD_INFO fallback for device_id=%s', did)
            if self._device_info_via_relay(did, dkey):
                return

        _LOGGER.warning(
            'Could not retrieve device info for %s via UDP or relay.', self._ip
        )

    def _normalize_state(self, data: dict) -> dict:
        """Normalise relay response data to plain integer values.

        Some firmware versions return certain dpid values as hex-encoded
        strings (e.g. color temp as "03e8") or out-of-range integers.
        We convert hex strings to ints and drop values > 100 000 so that
        the platform code can use plain arithmetic on all returned values.
        """
        MAX_VALID = 100_000
        result = {}
        for k, v in data.items():
            if isinstance(v, int) and 0 <= v <= MAX_VALID:
                result[k] = v
            elif isinstance(v, str):
                try:
                    int_val = int(v, 16)
                    if 0 <= int_val <= MAX_VALID:
                        result[k] = int_val
                except ValueError:
                    pass
        return result

    def _send_relay(self, cmd_dict: dict) -> dict:
        """Publish *cmd_dict* to the relay and return the device response data.

        Blocks until the relay forwards the device's reply (matched by sn)
        or a 5-second timeout expires.
        """
        with self._lock:
            if self._connect is None:
                _LOGGER.info('_send_relay: no relay connection')
                return {}
            if not self._device_id or not self._device_key:
                _LOGGER.info('_send_relay: missing device_id or device_key')
                return {}

            sn = get_sn()
            cmd_dict['sn'] = sn
            message = json.dumps(cmd_dict, separators=(',', ':'))
            line = (
                'cmd=publish'
                '&device_id=' + self._device_id +
                '&topic=control_' + self._device_id +
                '&device_key=' + self._device_key +
                '&message=' + message + '\r\n'
            )

            try:
                self._connect.sendall(line.encode())
            except Exception as e:
                _LOGGER.info('_send_relay send error: %s', e)
                self._close_connection()
                self._reconnect()
                return {}

            # Read response lines; skip relay acks and keepalives
            deadline = time.time() + 5
            buf = self._recv_buf
            try:
                while time.time() < deadline:
                    remaining = deadline - time.time()
                    self._connect.settimeout(max(0.1, remaining))
                    try:
                        chunk = self._connect.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                    except socket.timeout:
                        continue

                    # Process all complete lines in the buffer
                    while b'\r\n' in buf:
                        raw_line, buf = buf.split(b'\r\n', 1)
                        if not raw_line:
                            continue
                        parts = _parse_relay_line(
                            raw_line.decode('utf-8', errors='replace')
                        )
                        if (
                            parts.get('cmd') == 'publish'
                            and parts.get('device_id') == self._device_id
                            and parts.get('topic') == 'device_' + self._device_id
                            and 'message' in parts
                        ):
                            try:
                                msg_obj = json.loads(parts['message'])
                                if msg_obj.get('sn') == sn:
                                    self._recv_buf = buf
                                    data = msg_obj.get('msg', {}).get('data', {})
                                    return self._normalize_state(data) if isinstance(data, dict) else {}
                            except (json.JSONDecodeError, AttributeError):
                                pass

            except Exception as e:
                _LOGGER.info('_send_relay recv error: %s', e)
                self._close_connection()
                self._reconnect()
                return {}
            finally:
                try:
                    self._connect.settimeout(None)
                except Exception:
                    pass

            self._recv_buf = buf
            return {}

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def check(self) -> bool:
        return True

    @property
    def dpid(self):
        return self._dpid

    @property
    def device_model_name(self):
        return self._device_model_name

    @property
    def icon(self):
        return self._icon

    @property
    def device_type_code(self) -> str:
        return self._device_type_code

    @property
    def device_id(self):
        return self._device_id

    # ------------------------------------------------------------------
    # Public API used by platforms
    # ------------------------------------------------------------------

    def query(self) -> dict:
        """Query the full device state via cloud relay.

        Returns a dict of {dpid: int_value} normalised to plain integers.
        """
        return self._send_relay({'cmd': CMD_QUERY, 'pv': 0, 'msg': {'attr': [0]}})

    def control(self, payload: dict) -> bool:
        """Send a CMD_SET to the device via cloud relay.

        *payload* is a dict of {dpid_str: int_value}, e.g. {'1': 1, '4': 500}.
        Returns True if the send succeeded (does not wait for device ack).
        """
        if self._connect is None:
            _LOGGER.info('control: no relay connection')
            return False
        if not self._device_id or not self._device_key:
            return False
        try:
            sn = get_sn()
            message = json.dumps(
                {
                    'cmd': CMD_SET,
                    'pv': 0,
                    'sn': sn,
                    'msg': {
                        'attr': [int(k) for k in payload.keys()],
                        'data': payload,
                    },
                },
                separators=(',', ':'),
            )
            line = (
                'cmd=publish'
                '&device_id=' + self._device_id +
                '&topic=control_' + self._device_id +
                '&device_key=' + self._device_key +
                '&message=' + message + '\r\n'
            )
            self._connect.sendall(line.encode())
            return True
        except Exception as e:
            _LOGGER.info('control error: %s', e)
            self._close_connection()
            self._reconnect()
            return False
