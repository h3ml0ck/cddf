import struct
import pytest

import drone_tools.drone_wifi_remote_id as wifi


# -------------------------------------------------------
# parse_remote_id_element
# -------------------------------------------------------

def test_parse_remote_id_element_too_short():
    assert wifi.parse_remote_id_element(b'\x90\x3a') is None


def test_parse_remote_id_element_wrong_oui():
    data = b'\x00\x11\x22\x00' + b'\x00' * 20
    assert wifi.parse_remote_id_element(data) is None


def test_parse_remote_id_element_unknown_type_returns_hex():
    # OUI + type 0xFF + 4 bytes of data
    data = wifi.REMOTE_ID_OUI + b'\xff' + b'\xde\xad\xbe\xef'
    result = wifi.parse_remote_id_element(data)
    assert result is not None
    assert result['raw_type'] == 0xFF
    assert result['raw_data'] == 'deadbeef'


def test_parse_remote_id_element_empty_payload():
    # OUI + type only, no payload
    data = wifi.REMOTE_ID_OUI + b'\x03'
    result = wifi.parse_remote_id_element(data)
    assert result is not None
    assert result['data_length'] == 0


# -------------------------------------------------------
# parse_basic_id
# -------------------------------------------------------

def _make_basic_id_element(ua_type: int, id_type: int, uas_id: str) -> bytes:
    id_bytes = uas_id.encode('utf-8')[:20].ljust(20, b'\x00')
    msg_data = bytes([ua_type, id_type]) + id_bytes
    return wifi.REMOTE_ID_OUI + b'\x00' + msg_data


def test_parse_basic_id_serial_number():
    data = _make_basic_id_element(ua_type=4, id_type=1, uas_id="SN-12345")
    result = wifi.parse_remote_id_element(data)
    assert result['message_type'] == 'Basic ID'
    assert result['ua_type'] == 'VTOL'
    assert result['id_type'] == 'Serial Number'
    assert result['uas_id'] == 'SN-12345'


def test_parse_basic_id_unknown_types():
    data = _make_basic_id_element(ua_type=99, id_type=99, uas_id="X")
    result = wifi.parse_remote_id_element(data)
    assert 'Unknown' in result['ua_type']
    assert 'Unknown' in result['id_type']


def test_parse_basic_id_trims_null_padding():
    data = _make_basic_id_element(ua_type=2, id_type=2, uas_id="ABC")
    result = wifi.parse_remote_id_element(data)
    assert result['uas_id'] == 'ABC'


# -------------------------------------------------------
# parse_location_vector
# -------------------------------------------------------

def _make_location_element(status=1, direction_deg=90.0, speed_h=5.0, speed_v=-1.0,
                            lat=37.7749, lon=-122.4194, alt=100.0, height=50.0) -> bytes:
    msg_data = bytes([status])
    msg_data += struct.pack('<H', int(direction_deg * 100))
    msg_data += struct.pack('<H', int(speed_h * 100))
    msg_data += struct.pack('<h', int(speed_v * 100))
    msg_data += struct.pack('<i', int(lat * 1e7))
    msg_data += struct.pack('<i', int(lon * 1e7))
    msg_data += struct.pack('<h', int(alt * 2))
    msg_data += struct.pack('<h', int(height * 2))
    msg_data = msg_data.ljust(25, b'\x00')  # parser requires >= 25 bytes
    return wifi.REMOTE_ID_OUI + b'\x01' + msg_data


def test_parse_location_vector_values():
    data = _make_location_element(direction_deg=180.0, speed_h=10.0, lat=48.8566, lon=2.3522,
                                   alt=200.0, height=80.0)
    result = wifi.parse_remote_id_element(data)
    assert result['message_type'] == 'Location/Vector'
    assert result['direction'] == pytest.approx(180.0, abs=0.01)
    assert result['speed_horizontal'] == pytest.approx(10.0, abs=0.01)
    assert result['latitude'] == pytest.approx(48.8566, abs=1e-4)
    assert result['longitude'] == pytest.approx(2.3522, abs=1e-4)
    assert result['altitude'] == pytest.approx(200.0, abs=0.5)
    assert result['height'] == pytest.approx(80.0, abs=0.5)


def test_parse_location_vector_too_short_falls_back_to_raw():
    # Only 10 bytes of payload — below the 25-byte threshold
    short_data = wifi.REMOTE_ID_OUI + b'\x01' + b'\x00' * 10
    result = wifi.parse_remote_id_element(short_data)
    assert result is not None
    assert 'raw_data' in result


# -------------------------------------------------------
# parse_self_id
# -------------------------------------------------------

def _make_self_id_element(desc_type: int, description: str) -> bytes:
    msg_data = bytes([desc_type]) + description.encode('utf-8')
    return wifi.REMOTE_ID_OUI + b'\x03' + msg_data


def test_parse_self_id_text():
    data = _make_self_id_element(0, "Delivery drone")
    result = wifi.parse_remote_id_element(data)
    assert result['message_type'] == 'Self ID'
    assert result['description_type'] == 'Text'
    assert result['description'] == 'Delivery drone'


def test_parse_self_id_emergency():
    data = _make_self_id_element(1, "MAYDAY")
    result = wifi.parse_remote_id_element(data)
    assert result['description_type'] == 'Emergency'


def test_parse_self_id_unknown_desc_type():
    data = _make_self_id_element(99, "???")
    result = wifi.parse_remote_id_element(data)
    assert 'Unknown' in result['description_type']


# -------------------------------------------------------
# parse_operator_id
# -------------------------------------------------------

def _make_operator_id_element(op_id_type: int, operator_id: str) -> bytes:
    id_bytes = operator_id.encode('utf-8')[:20].ljust(20, b'\x00')
    msg_data = bytes([op_id_type]) + id_bytes
    return wifi.REMOTE_ID_OUI + b'\x05' + msg_data


def test_parse_operator_id():
    data = _make_operator_id_element(0, "OP-XYZ-789")
    result = wifi.parse_remote_id_element(data)
    assert result['message_type'] == 'Operator ID'
    assert result['operator_id'] == 'OP-XYZ-789'
    assert result['operator_id_type'] == 0


def test_parse_operator_id_trims_null_padding():
    data = _make_operator_id_element(1, "SHORT")
    result = wifi.parse_remote_id_element(data)
    assert result['operator_id'] == 'SHORT'
