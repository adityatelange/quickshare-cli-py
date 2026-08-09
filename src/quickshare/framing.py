"""Wire framing: 4-byte big-endian length prefix + payload, used for every
message on the Quick Share TCP socket (handshake and encrypted alike)."""

from __future__ import annotations

import socket

# Not part of the protocol spec -- our own guard against a malicious/corrupt
# length prefix causing an oversized allocation. Same name and value as
# grishka/NearDrop's SANE_FRAME_LENGTH (NearbyShare/NearbyConnection.swift).
# Cited here only as prior art for this defensive bound, not as a source for
# protocol logic.
MAX_FRAME_LENGTH = 5 * 1024 * 1024


class FrameError(Exception):
    pass


def pack_frame(payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "big") + payload


def send_frame(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(pack_frame(payload))


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise FrameError("connection closed while reading frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_frame(sock: socket.socket) -> bytes:
    length = int.from_bytes(_recv_exact(sock, 4), "big")
    if length > MAX_FRAME_LENGTH:
        raise FrameError(f"frame length {length} exceeds max {MAX_FRAME_LENGTH}")
    return _recv_exact(sock, length)
