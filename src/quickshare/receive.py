"""Post-handshake receive flow: connection response, paired-key exchange,
file introduction/consent, payload transfer, and file writing to disk.

Frame layering: location.nearby.connections.OfflineFrame (transport control,
offline_wire_formats.proto) carries payload_transfer chunks whose bodies,
once reassembled, are sharing.nearby.Frame messages (wire_format.proto) --
the application-level protocol (introduction, accept/reject, paired-key).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from quickshare import crypto
from quickshare.proto import offline_wire_formats_pb2 as off_pb2
from quickshare.proto import wire_format_pb2 as wf_pb2
from quickshare.secure_frame import SecureChannel


class ReceiveError(Exception):
    pass


def build_connection_response_accept() -> bytes:
    """Plaintext OfflineFrame -- sent BEFORE the secure channel is used for reads."""
    frame = off_pb2.OfflineFrame(
        version=off_pb2.OfflineFrame.Version.V1,
        v1=off_pb2.V1Frame(
            type=off_pb2.V1Frame.FrameType.CONNECTION_RESPONSE,
            connection_response=off_pb2.ConnectionResponseFrame(
                response=off_pb2.ConnectionResponseFrame.ResponseStatus.ACCEPT,
                os_info=off_pb2.OsInfo(type=off_pb2.OsInfo.OsType.LINUX),
            ),
        ),
    )
    return frame.SerializeToString()


def parse_offline_frame(data: bytes) -> off_pb2.OfflineFrame:
    frame = off_pb2.OfflineFrame()
    frame.ParseFromString(data)
    return frame


def build_paired_key_encryption_frame() -> list[bytes]:
    """Random secret_id_hash/signed_data -- receiver doesn't verify these, and since
    we always report PairedKeyResult.UNABLE, our own random values are never checked either."""
    inner = wf_pb2.Frame(
        version=wf_pb2.Frame.Version.V1,
        v1=wf_pb2.V1Frame(
            type=wf_pb2.V1Frame.FrameType.PAIRED_KEY_ENCRYPTION,
            paired_key_encryption=wf_pb2.PairedKeyEncryptionFrame(
                secret_id_hash=crypto.random_bytes(6),
                signed_data=crypto.random_bytes(72),
            ),
        ),
    )
    return _wrap_offline_bytes_payload(inner.SerializeToString())


def build_paired_key_result_frame() -> list[bytes]:
    inner = wf_pb2.Frame(
        version=wf_pb2.Frame.Version.V1,
        v1=wf_pb2.V1Frame(
            type=wf_pb2.V1Frame.FrameType.PAIRED_KEY_RESULT,
            paired_key_result=wf_pb2.PairedKeyResultFrame(
                status=wf_pb2.PairedKeyResultFrame.Status.UNABLE,
            ),
        ),
    )
    return _wrap_offline_bytes_payload(inner.SerializeToString())


def build_payload_canceled(payload_id: int) -> bytes:
    """OfflineFrame carrying a PayloadTransferFrame CONTROL message with
    PAYLOAD_CANCELED, so the sender learns we aborted rather than just
    silently dropping the connection."""
    return off_pb2.OfflineFrame(
        version=off_pb2.OfflineFrame.Version.V1,
        v1=off_pb2.V1Frame(
            type=off_pb2.V1Frame.FrameType.PAYLOAD_TRANSFER,
            payload_transfer=off_pb2.PayloadTransferFrame(
                packet_type=off_pb2.PayloadTransferFrame.PacketType.CONTROL,
                payload_header=off_pb2.PayloadTransferFrame.PayloadHeader(id=payload_id),
                control_message=off_pb2.PayloadTransferFrame.ControlMessage(
                    event=off_pb2.PayloadTransferFrame.ControlMessage.EventType.PAYLOAD_CANCELED,
                ),
            ),
        ),
    ).SerializeToString()


def build_payload_received_ack(payload_id: int, offset: int) -> bytes:
    """OfflineFrame carrying a PayloadTransferFrame CONTROL message with
    PAYLOAD_RECEIVED_ACK -- sent once a FILE payload is fully written, so the
    sender knows the transfer genuinely completed rather than timing out and
    reporting it declined."""
    return off_pb2.OfflineFrame(
        version=off_pb2.OfflineFrame.Version.V1,
        v1=off_pb2.V1Frame(
            type=off_pb2.V1Frame.FrameType.PAYLOAD_TRANSFER,
            payload_transfer=off_pb2.PayloadTransferFrame(
                packet_type=off_pb2.PayloadTransferFrame.PacketType.CONTROL,
                payload_header=off_pb2.PayloadTransferFrame.PayloadHeader(id=payload_id),
                control_message=off_pb2.PayloadTransferFrame.ControlMessage(
                    event=off_pb2.PayloadTransferFrame.ControlMessage.EventType.PAYLOAD_RECEIVED_ACK,
                    offset=offset,
                ),
            ),
        ),
    ).SerializeToString()


def build_connection_response_frame(accept: bool) -> list[bytes]:
    """The sharing_nearby (application-level) accept/reject response -- distinct from
    build_connection_response_accept, which is the earlier transport-level ConnectionResponse."""
    status = wf_pb2.ConnectionResponseFrame.Status.ACCEPT if accept else wf_pb2.ConnectionResponseFrame.Status.REJECT
    inner = wf_pb2.Frame(
        version=wf_pb2.Frame.Version.V1,
        v1=wf_pb2.V1Frame(
            type=wf_pb2.V1Frame.FrameType.RESPONSE,
            connection_response=wf_pb2.ConnectionResponseFrame(status=status),
        ),
    )
    return _wrap_offline_bytes_payload(inner.SerializeToString())


_bytes_payload_id_counter = 0


def _next_bytes_payload_id() -> int:
    global _bytes_payload_id_counter
    _bytes_payload_id_counter -= 1  # negative, to avoid colliding with sender's file payload ids
    return _bytes_payload_id_counter


def _wrap_offline_bytes_payload(sharing_frame_bytes: bytes) -> list[bytes]:
    """Wrap a serialized sharing_nearby.Frame as a one-shot BYTES PayloadTransferFrame.

    Returns two separately-serialized OfflineFrame byte-strings -- a data chunk and an
    empty LAST_CHUNK terminator -- each of which the caller must encrypt (SecureChannel.encrypt)
    and send as its own framed message, matching how the sender emits two PayloadTransferFrames
    per logical control frame.
    """
    payload_id = _next_bytes_payload_id()

    data_frame = off_pb2.OfflineFrame(
        version=off_pb2.OfflineFrame.Version.V1,
        v1=off_pb2.V1Frame(
            type=off_pb2.V1Frame.FrameType.PAYLOAD_TRANSFER,
            payload_transfer=off_pb2.PayloadTransferFrame(
                packet_type=off_pb2.PayloadTransferFrame.PacketType.DATA,
                payload_header=off_pb2.PayloadTransferFrame.PayloadHeader(
                    id=payload_id,
                    type=off_pb2.PayloadTransferFrame.PayloadHeader.PayloadType.BYTES,
                    total_size=len(sharing_frame_bytes),
                ),
                payload_chunk=off_pb2.PayloadTransferFrame.PayloadChunk(
                    flags=0,
                    offset=0,
                    body=sharing_frame_bytes,
                ),
            ),
        ),
    )
    terminator = off_pb2.OfflineFrame(
        version=off_pb2.OfflineFrame.Version.V1,
        v1=off_pb2.V1Frame(
            type=off_pb2.V1Frame.FrameType.PAYLOAD_TRANSFER,
            payload_transfer=off_pb2.PayloadTransferFrame(
                packet_type=off_pb2.PayloadTransferFrame.PacketType.DATA,
                payload_header=off_pb2.PayloadTransferFrame.PayloadHeader(
                    id=payload_id,
                    type=off_pb2.PayloadTransferFrame.PayloadHeader.PayloadType.BYTES,
                    total_size=len(sharing_frame_bytes),
                ),
                payload_chunk=off_pb2.PayloadTransferFrame.PayloadChunk(
                    flags=off_pb2.PayloadTransferFrame.PayloadChunk.Flags.LAST_CHUNK,
                    offset=len(sharing_frame_bytes),
                    body=b"",
                ),
            ),
        ),
    )
    return [data_frame.SerializeToString(), terminator.SerializeToString()]


PARTIAL_SUFFIX = ".part"


@dataclass
class IncomingFile:
    payload_id: int
    name: str
    size: int
    dest_path: Path
    _fh: object = field(default=None, repr=False)
    bytes_written: int = 0
    started_at: float = field(default=0.0, repr=False)

    @property
    def partial_path(self) -> Path:
        """Written to under this name (dest_path + '.part') until the transfer
        completes, so a transfer that's canceled or cut off mid-way never
        leaves behind a file that looks complete under its real name."""
        return self.dest_path.with_name(self.dest_path.name + PARTIAL_SUFFIX)

    def open(self) -> None:
        self.dest_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.partial_path, "wb")
        self.started_at = time.monotonic()

    def write_chunk(self, offset: int, data: bytes) -> None:
        self._fh.seek(offset)
        self._fh.write(data)
        self.bytes_written += len(data)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def finalize(self) -> None:
        """Call once fully received: atomically rename .part -> the real name."""
        self.close()
        self.partial_path.rename(self.dest_path)

    def discard(self) -> None:
        """Call on cancel/abort: remove the partial file instead of finalizing it."""
        self.close()
        self.partial_path.unlink(missing_ok=True)

    @property
    def complete(self) -> bool:
        return self.bytes_written >= self.size

    @property
    def speed_bps(self) -> float:
        """Average transfer speed in bytes/sec since this file started."""
        elapsed = time.monotonic() - self.started_at
        return self.bytes_written / elapsed if elapsed > 0 else 0.0


def unique_destination(output_dir: Path, name: str) -> Path:
    """Avoid clobbering existing files: 'photo.jpg' -> 'photo (1).jpg' -> 'photo (2).jpg' ..."""
    candidate = output_dir / name
    if not candidate.exists():
        return candidate
    stem, ext = os.path.splitext(name)
    n = 1
    while True:
        candidate = output_dir / f"{stem} ({n}){ext}"
        if not candidate.exists():
            return candidate
        n += 1


SENDER_CANCELED = "sender_canceled"


@dataclass
class ReceiveSession:
    channel: SecureChannel
    output_dir: Path
    pin: str
    auto_accept: bool = False
    on_offer: Optional[Callable[[list[wf_pb2.FileMetadata], str], bool]] = None
    on_progress: Optional[Callable[[IncomingFile], None]] = None

    files_by_payload_id: dict = field(default_factory=dict)
    _bytes_reassembly: dict = field(default_factory=dict)  # payload_id -> bytearray
    _offer_accepted: bool = field(default=False, repr=False)

    def handle_encrypted_frame(self, secure_message_bytes: bytes) -> Optional[list[Path] | str]:
        """Feed one encrypted OfflineFrame off the wire. Returns a list of completed
        file paths once all offered files have been fully received, SENDER_CANCELED
        if the sender explicitly canceled a payload, or None if still in progress."""
        offline_frame_bytes = self.channel.decrypt(secure_message_bytes)
        frame = parse_offline_frame(offline_frame_bytes)

        if frame.v1.type != off_pb2.V1Frame.FrameType.PAYLOAD_TRANSFER:
            return None

        return self._handle_payload_transfer(frame.v1.payload_transfer)

    def _handle_payload_transfer(self, pt: off_pb2.PayloadTransferFrame) -> Optional[list[Path] | str]:
        header = pt.payload_header
        chunk = pt.payload_chunk
        is_last = bool(chunk.flags & off_pb2.PayloadTransferFrame.PayloadChunk.Flags.LAST_CHUNK)

        if pt.packet_type == off_pb2.PayloadTransferFrame.PacketType.CONTROL:
            event = pt.control_message.event
            if event in (
                off_pb2.PayloadTransferFrame.ControlMessage.EventType.PAYLOAD_CANCELED,
                off_pb2.PayloadTransferFrame.ControlMessage.EventType.PAYLOAD_ERROR,
            ):
                incoming = self.files_by_payload_id.pop(header.id, None)
                if incoming is not None:
                    incoming.discard()
                return SENDER_CANCELED
            return None

        if header.type == off_pb2.PayloadTransferFrame.PayloadHeader.PayloadType.BYTES:
            buf = self._bytes_reassembly.setdefault(header.id, bytearray())
            if chunk.body:
                buf.extend(chunk.body)
            if is_last:
                sharing_bytes = bytes(self._bytes_reassembly.pop(header.id))
                self._handle_sharing_frame(sharing_bytes)
            return None

        if header.type == off_pb2.PayloadTransferFrame.PayloadHeader.PayloadType.FILE:
            incoming = self.files_by_payload_id.get(header.id)
            if incoming is None:
                raise ReceiveError(f"received FILE payload chunk for unknown payload_id {header.id}")
            if chunk.body:
                incoming.write_chunk(chunk.offset, chunk.body)
                if self.on_progress:
                    self.on_progress(incoming)
            if is_last or incoming.complete:
                if incoming.complete:
                    incoming.finalize()
                else:
                    incoming.close()
                self.channel_send(self.channel.encrypt(build_payload_received_ack(header.id, incoming.bytes_written)))
                if self._offer_accepted and all(f.complete for f in self.files_by_payload_id.values()):
                    return [f.dest_path for f in self.files_by_payload_id.values()]
        return None

    def _handle_sharing_frame(self, sharing_bytes: bytes) -> None:
        frame = wf_pb2.Frame()
        frame.ParseFromString(sharing_bytes)

        if frame.v1.type == wf_pb2.V1Frame.FrameType.PAIRED_KEY_ENCRYPTION:
            self._send_frames(build_paired_key_result_frame())
        elif frame.v1.type == wf_pb2.V1Frame.FrameType.INTRODUCTION:
            self._handle_introduction(frame.v1.introduction)

    def _handle_introduction(self, introduction: wf_pb2.IntroductionFrame) -> None:
        if self.on_offer is not None:
            accept = self.on_offer(list(introduction.file_metadata), self.pin)
        else:
            accept = self.auto_accept

        self._offer_accepted = accept
        if accept:
            for meta in introduction.file_metadata:
                dest = unique_destination(self.output_dir, meta.name or f"file-{meta.payload_id}")
                incoming = IncomingFile(payload_id=meta.payload_id, name=meta.name, size=meta.size, dest_path=dest)
                incoming.open()
                self.files_by_payload_id[meta.payload_id] = incoming

        self._send_frames(build_connection_response_frame(accept))

    def start(self) -> None:
        """Call once, right after the plaintext ConnectionResponse has been sent
        and the SecureChannel is ready, to kick off the paired-key exchange."""
        self._send_frames(build_paired_key_encryption_frame())

    def cancel(self) -> None:
        """User-initiated abort mid-transfer: tell the sender we canceled each
        in-progress file, then discard the .part partial data we'd written for it."""
        for payload_id, incoming in self.files_by_payload_id.items():
            if not incoming.complete:
                try:
                    self.channel_send(self.channel.encrypt(build_payload_canceled(payload_id)))
                except Exception:
                    pass  # best-effort notification; we're tearing the connection down regardless
                incoming.discard()

    def discard_incomplete(self) -> None:
        """Clean up .part partials with no attempt to notify the peer -- for
        when the connection is already gone (e.g. the sender disconnected)."""
        for incoming in self.files_by_payload_id.values():
            if not incoming.complete:
                incoming.discard()

    def _send_frames(self, offline_frames: list[bytes]) -> None:
        for frame_bytes in offline_frames:
            self.channel_send(self.channel.encrypt(frame_bytes))

    # Set by the server glue: given a fully-encrypted SecureMessage, write it
    # framed (4-byte length prefix) to the socket.
    channel_send: Callable[[bytes], None] = field(default=None, repr=False)
