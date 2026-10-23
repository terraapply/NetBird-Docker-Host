import ipaddress
import struct

import deploy

MAGIC = 0x2112A442


def xor_mapped(ip, port):
    value = struct.pack("!BBHI", 0, 1, port ^ 0x2112,
                        int(ipaddress.IPv4Address(ip)) ^ MAGIC)
    return struct.pack("!HH", 0x0020, len(value)) + value


def test_xor_mapped_ipv4():
    assert deploy._parse_xor_mapped(xor_mapped("203.0.113.10", 41234)) == "203.0.113.10:41234"


def test_mapped_address_fallback():
    attr = struct.pack("!HH", 0x0001, 8) + struct.pack("!BBH4B", 0, 1, 3478, 198, 51, 100, 7)
    assert deploy._parse_xor_mapped(attr) == "198.51.100.7:3478"


def test_ipv6_only_returns_none():
    value = struct.pack("!BBH", 0, 2, 41234 ^ 0x2112) + bytes(16)
    attr = struct.pack("!HH", 0x0020, len(value)) + value
    assert deploy._parse_xor_mapped(attr) is None


def test_skips_unknown_attribute_with_padding():
    unknown = struct.pack("!HH", 0x8022, 5) + b"abcde" + bytes(3)
    attrs = unknown + xor_mapped("203.0.113.10", 41234)
    assert deploy._parse_xor_mapped(attrs) == "203.0.113.10:41234"
