"""
Solarman V5 Protocol Implementation for SunSynk / Deye Inverters over Wi-Fi.
Encapsulates Modbus RTU commands inside Solarman V5 frames and sends them via TCP/UDP port 8899.
"""

import struct
import socket
import asyncio
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger("SolarmanV5")

def calc_modbus_crc(data: bytes) -> bytes:
    """Calculate 16-bit Modbus CRC (little-endian)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack("<H", crc)

def calc_solarman_checksum(data: bytes) -> int:
    """Calculate Solarman V5 1-byte checksum (sum of bytes % 256)."""
    return sum(data) & 0xFF

class SolarmanV5:
    """Client for communicating with Sunsynk / Solarman Wi-Fi loggers."""

    START_BYTE = 0xA5
    END_BYTE = 0x15
    CONTROL_REQ = 0x4510
    CONTROL_RESP = 0x1510

    def __init__(self, host: str, serial_number: int, port: int = 8899, slave_id: int = 1, timeout: float = 4.0):
        self.host = host
        self.port = port
        self.serial_number = serial_number
        self.slave_id = slave_id
        self.timeout = timeout
        self._seq = 1

    def _build_modbus_read(self, start_reg: int, count: int) -> bytes:
        """Build Modbus Function 0x03 Read Holding Registers frame."""
        payload = struct.pack(">BBHH", self.slave_id, 0x03, start_reg, count)
        crc = calc_modbus_crc(payload)
        return payload + crc

    def _build_modbus_write_single(self, reg: int, val: int) -> bytes:
        """Build Modbus Function 0x06 Write Single Register frame."""
        payload = struct.pack(">BBHH", self.slave_id, 0x06, reg, val)
        crc = calc_modbus_crc(payload)
        return payload + crc

    def _build_modbus_write_multiple(self, start_reg: int, values: List[int]) -> bytes:
        """Build Modbus Function 0x10 Write Multiple Registers frame."""
        byte_count = len(values) * 2
        header = struct.pack(">BBHHB", self.slave_id, 0x10, start_reg, len(values), byte_count)
        vals_bytes = b"".join(struct.pack(">H", v) for v in values)
        payload = header + vals_bytes
        crc = calc_modbus_crc(payload)
        return payload + crc

    def _build_solarman_packet(self, modbus_payload: bytes) -> bytes:
        """Wrap Modbus payload in a Solarman V5 frame."""
        # Solarman header payload:
        # 2 bytes control code (0x4510)
        # 2 bytes sequence number
        # 4 bytes serial number (uint32 LE)
        # 1 byte frame type (0x02 Modbus)
        # 2 bytes sensor type (0x0000)
        # 4 bytes delivery time (0)
        # 4 bytes power on time (0)
        # 4 bytes offset time (0)
        # Total header = 21 bytes
        header_content = struct.pack(
            "<HHIBHIII",
            self.CONTROL_REQ,
            self._seq,
            self.serial_number,
            0x02,
            0x0000,
            0,
            0,
            0
        )
        self._seq = (self._seq + 1) & 0xFFFF

        body = header_content + modbus_payload
        length = len(body)
        
        # Frame: START(1) + LENGTH(2 LE) + BODY + CHECKSUM(1) + END(1)
        length_bytes = struct.pack("<H", length)
        packet_for_checksum = length_bytes + body
        checksum = calc_solarman_checksum(packet_for_checksum)
        
        return bytes([self.START_BYTE]) + packet_for_checksum + bytes([checksum, self.END_BYTE])

    def _parse_solarman_response(self, response: bytes) -> Optional[bytes]:
        """Validate and strip Solarman V5 frame to extract Modbus RTU response."""
        if len(response) < 28:
            logger.warning(f"Response too short: {len(response)} bytes")
            return None
        
        if response[0] != self.START_BYTE or response[-1] != self.END_BYTE:
            logger.warning("Invalid start or end byte in response")
            return None
        
        # Verify checksum
        body_to_check = response[1:-2]
        expected_checksum = response[-2]
        if calc_solarman_checksum(body_to_check) != expected_checksum:
            logger.warning("Solarman checksum mismatch")
            return None

        # Modbus response starts after Solarman header (offset 25)
        # Header: Start(1) + Length(2) + Control(2) + Seq(2) + SN(4) + Type(1) + Sensor(2) + Times(12) = 26 bytes
        modbus_resp = response[25:-2]
        if len(modbus_resp) < 5:
            logger.warning(f"Modbus payload in response too short: {len(modbus_resp)} bytes")
            return None
        
        # Verify Modbus CRC
        payload_data = modbus_resp[:-2]
        expected_crc = modbus_resp[-2:]
        if calc_modbus_crc(payload_data) != expected_crc:
            logger.warning("Modbus CRC mismatch in response")
            return None
        
        return modbus_resp

    async def _send_receive_tcp(self, packet: bytes) -> Optional[bytes]:
        """Send packet via TCP to logger port 8899 and read response."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout
            )
            writer.write(packet)
            await writer.drain()

            resp = await asyncio.wait_for(reader.read(1024), timeout=self.timeout)
            writer.close()
            await writer.wait_closed()
            return resp
        except Exception as e:
            logger.debug(f"TCP query failed to {self.host}:{self.port} - {e}")
            return None

    async def _send_receive_udp(self, packet: bytes) -> Optional[bytes]:
        """Send packet via UDP to logger port 8899 and receive response."""
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            await loop.sock_connect(sock, (self.host, self.port))
            await loop.sock_sendall(sock, packet)
            
            fut = loop.create_future()
            def on_readable():
                try:
                    data = sock.recv(1024)
                    if not fut.done():
                        fut.set_result(data)
                except Exception as ex:
                    if not fut.done():
                        fut.set_exception(ex)
                finally:
                    loop.remove_reader(sock.fileno())

            loop.add_reader(sock.fileno(), on_readable)
            resp = await asyncio.wait_for(fut, timeout=self.timeout)
            return resp
        except Exception as e:
            logger.debug(f"UDP query failed to {self.host}:{self.port} - {e}")
            return None
        finally:
            try:
                loop.remove_reader(sock.fileno())
            except Exception:
                pass
            sock.close()

    async def query(self, modbus_payload: bytes, use_tcp: bool = True) -> Optional[bytes]:
        """Send Modbus request wrapped in Solarman V5 frame and return raw Modbus response."""
        packet = self._build_solarman_packet(modbus_payload)
        
        resp = await self._send_receive_tcp(packet) if use_tcp else None
        if not resp:
            # Fallback to UDP if TCP is unanswered
            resp = await self._send_receive_udp(packet)
            
        if not resp:
            return None
        
        return self._parse_solarman_response(resp)

    async def read_holding_registers(self, start_reg: int, count: int) -> Optional[List[int]]:
        """Read holding registers (Function 0x03) and return list of 16-bit uint values."""
        req = self._build_modbus_read(start_reg, count)
        modbus_resp = await self.query(req)
        if not modbus_resp:
            return None
        
        # Modbus 0x03 response: Slave(1) + Func(1) + ByteCount(1) + [2 bytes per reg] + CRC(2)
        if len(modbus_resp) < 5 or modbus_resp[1] != 0x03:
            logger.warning(f"Unexpected Modbus function code in response: {modbus_resp[1] if len(modbus_resp) > 1 else 'None'}")
            return None
        
        byte_count = modbus_resp[2]
        reg_data = modbus_resp[3:3 + byte_count]
        regs = []
        for i in range(0, len(reg_data), 2):
            val = struct.unpack(">H", reg_data[i:i+2])[0]
            regs.append(val)
        return regs

    async def write_single_register(self, reg: int, val: int) -> bool:
        """Write single holding register (Function 0x06)."""
        req = self._build_modbus_write_single(reg, val)
        modbus_resp = await self.query(req)
        if not modbus_resp:
            return False
        # Expected echo of function 0x06
        return len(modbus_resp) >= 6 and modbus_resp[1] == 0x06

    async def write_multiple_registers(self, start_reg: int, values: List[int]) -> bool:
        """Write multiple holding registers (Function 0x10)."""
        req = self._build_modbus_write_multiple(start_reg, values)
        modbus_resp = await self.query(req)
        if not modbus_resp:
            return False
        return len(modbus_resp) >= 6 and modbus_resp[1] == 0x10
