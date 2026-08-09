"""UKEY2 handshake, receiver (server) side.

Sequence: ConnectionRequest (plaintext OfflineFrame) -> Ukey2ClientInit ->
Ukey2ServerInit -> Ukey2ClientFinished -> ConnectionResponse (plaintext).
After this, all frames are wrapped in SecureMessage via secure_frame.SecureChannel.

Message validation and the ClientFinished commitment check follow
third_party/ukey2/ukey2/src/main/cpp/src/securegcm/ukey2_handshake.cc in
https://github.com/google/nearby (that path vendors github.com/google/ukey2
as a submodule) -- see crypto.py for the key-derivation constants sourced
from the same file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from quickshare import crypto
from quickshare.proto import securemessage_pb2
from quickshare.proto import ukey_pb2

_UKEY2_MESSAGE_TYPE_NAMES = {v.number: v.name for v in ukey_pb2.Ukey2Message.Type.DESCRIPTOR.values}


class Ukey2Error(Exception):
    pass


def _parse_p256_public_key(generic: securemessage_pb2.GenericPublicKey) -> "crypto.ec.EllipticCurvePublicKey":
    if generic.type != securemessage_pb2.EC_P256 or not generic.HasField("ec_p256_public_key"):
        raise Ukey2Error("peer public key is not EC_P256")
    ec_key = generic.ec_p256_public_key
    x = crypto.decode_point_unsigned(ec_key.x, 32)
    y = crypto.decode_point_unsigned(ec_key.y, 32)
    return crypto.public_key_from_xy(x, y)


def _encode_p256_public_key(pub: "crypto.ec.EllipticCurvePublicKey") -> bytes:
    x, y = crypto.public_key_xy(pub)
    generic = securemessage_pb2.GenericPublicKey(
        type=securemessage_pb2.EC_P256,
        ec_p256_public_key=securemessage_pb2.EcP256PublicKey(
            x=crypto.encode_point_signed(x),
            y=crypto.encode_point_signed(y),
        ),
    )
    return generic.SerializeToString()


@dataclass
class HandshakeResult:
    keys: crypto.D2DKeys


def parse_client_init(raw_message_bytes: bytes) -> ukey_pb2.Ukey2ClientInit:
    """Validate the incoming Ukey2Message wraps a well-formed ClientInit. Returns the inner message."""
    msg = ukey_pb2.Ukey2Message()
    msg.ParseFromString(raw_message_bytes)

    if msg.message_type != ukey_pb2.Ukey2Message.Type.CLIENT_INIT:
        raise Ukey2Error(f"expected CLIENT_INIT, got {_UKEY2_MESSAGE_TYPE_NAMES.get(msg.message_type)}")

    client_init = ukey_pb2.Ukey2ClientInit()
    client_init.ParseFromString(msg.message_data)

    if client_init.version != 1:
        raise Ukey2Error(f"unsupported ClientInit version {client_init.version}")
    if len(client_init.random) != 32:
        raise Ukey2Error("ClientInit random must be 32 bytes")
    if client_init.next_protocol != "AES_256_CBC-HMAC_SHA256":
        raise Ukey2Error(f"unsupported next_protocol {client_init.next_protocol!r}")

    has_p256 = any(
        c.handshake_cipher == ukey_pb2.Ukey2HandshakeCipher.P256_SHA512
        for c in client_init.cipher_commitments
    )
    if not has_p256:
        raise Ukey2Error("ClientInit has no P256_SHA512 cipher commitment")

    return client_init


def find_p256_commitment(client_init: ukey_pb2.Ukey2ClientInit) -> bytes:
    for c in client_init.cipher_commitments:
        if c.handshake_cipher == ukey_pb2.Ukey2HandshakeCipher.P256_SHA512:
            return c.commitment
    raise Ukey2Error("no P256_SHA512 commitment present")


def build_server_init(server_public_key: "crypto.ec.EllipticCurvePublicKey") -> bytes:
    """Returns the raw serialized Ukey2Message (ServerInit) -- keep these exact bytes for key derivation."""
    server_init = ukey_pb2.Ukey2ServerInit(
        version=1,
        random=crypto.random_bytes(32),
        handshake_cipher=ukey_pb2.Ukey2HandshakeCipher.P256_SHA512,
        public_key=_encode_p256_public_key(server_public_key),
    )
    message = ukey_pb2.Ukey2Message(
        message_type=ukey_pb2.Ukey2Message.Type.SERVER_INIT,
        message_data=server_init.SerializeToString(),
    )
    return message.SerializeToString()


def verify_client_finished(
    raw_message_bytes: bytes, expected_commitment: bytes
) -> "crypto.ec.EllipticCurvePublicKey":
    """Checks sha512(raw ClientFinished Ukey2Message bytes) == the commitment from ClientInit,
    then returns the client's P-256 public key parsed from the message."""
    digest = hashlib.sha512(raw_message_bytes).digest()
    if digest != expected_commitment:
        raise Ukey2Error("cipher commitment mismatch: sha512(ClientFinished) != commitment")

    msg = ukey_pb2.Ukey2Message()
    msg.ParseFromString(raw_message_bytes)
    if msg.message_type != ukey_pb2.Ukey2Message.Type.CLIENT_FINISH:
        raise Ukey2Error(f"expected CLIENT_FINISH, got {_UKEY2_MESSAGE_TYPE_NAMES.get(msg.message_type)}")

    client_finished = ukey_pb2.Ukey2ClientFinished()
    client_finished.ParseFromString(msg.message_data)

    generic_key = securemessage_pb2.GenericPublicKey()
    generic_key.ParseFromString(client_finished.public_key)
    return _parse_p256_public_key(generic_key)


def run_server_handshake(
    client_init_bytes: bytes,
    send_server_init: "callable[[bytes], None]",
    recv_client_finished: "callable[[], bytes]",
) -> HandshakeResult:
    """Drives the full handshake given I/O callbacks. Returns derived D2D keys.

    send_server_init(raw_server_init_bytes) must write that exact frame to the socket.
    recv_client_finished() must return the raw next frame's bytes as read off the socket.
    """
    client_init = parse_client_init(client_init_bytes)
    commitment = find_p256_commitment(client_init)

    priv, pub = crypto.generate_keypair()
    server_init_bytes = build_server_init(pub)
    send_server_init(server_init_bytes)

    client_finished_bytes = recv_client_finished()
    client_pub = verify_client_finished(client_finished_bytes, commitment)

    shared_secret = crypto.ecdh_shared_secret(priv, client_pub)
    keys = crypto.derive_d2d_keys(shared_secret, client_init_bytes, server_init_bytes)
    return HandshakeResult(keys=keys)
