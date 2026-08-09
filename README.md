# quickshare-cli-py

A minimal, dependency-light Python receiver for **Google Quick Share** (formerly
Nearby Share) on Linux. Run it on a laptop or desktop with no Bluetooth adapter,
and Android phones on the same network can send files to it the same way they
send to another Android device or a ChromeOS/Windows machine.

Receive-only, single connection at a time, no GUI, built for a Linux desktop
that just needs to catch files from a phone.

## Why this exists

This has no GUI and no dependency on a desktop environment, so it runs on a
headless box or a minimal window manager, starts instantly, and stays out of
the way on a machine that just needs to catch a file from a phone.

## Features

- Advertises over mDNS (`_FC9F5ED42C8A._tcp.local.`) so phones on the same
  LAN/Wi-Fi discover this machine as a Quick Share target
- Full UKEY2 handshake (ECDH P-256 + HKDF-SHA256) and SecureMessage frame
  encryption (AES-256-CBC + HMAC-SHA256)
- PIN-verified consent prompt before accepting a transfer (or `--yes` to
  auto-accept)
- Live progress bar with percentage and transfer speed
- Cancel a transfer mid-flight (Ctrl+C on the receiver, or from the sender);
  either way the partial file is discarded, never left under its real name
- Stable device identity across restarts (derived from hostname, not MAC —
  no more re-pairing every time you restart the receiver)
- Colored terminal output (`--no-color` to disable)

## Requirements

- Linux, Python 3.10
- [uv](https://docs.astral.sh/uv/) for dependency management
- A network interface that can reach the sending phone (Wi-Fi or wired LAN —
  no Bluetooth needed)

## Setup

```sh
uv sync
```

This installs runtime dependencies (`zeroconf`, `protobuf`, `cryptography`)
and the dev-only `grpcio-tools`, used solely to regenerate the protobuf
bindings under `src/quickshare/proto/` (already checked in — you don't need
to regenerate them to just run the receiver).

## Usage

```sh
uv run quickshare receive
```

The phone must be on the same network and have Quick Share's visibility set
to allow "everyone" (or your account/contacts, depending on Android version).
When a transfer comes in you'll see a PIN to confirm on both devices, then a
progress bar as the file downloads.

Options:

```
uv run quickshare receive [-o OUTPUT_DIR] [-n NAME] [-i IFACE] [--yes] [--no-color]

  -o, --output-dir   Directory to save received files into (default: current directory)
  -n, --name         Device name to advertise (default: hostname)
  -i, --iface        Network interface to advertise on, e.g. enp6s0 (default: auto-detect)
  --yes              Auto-accept incoming transfers without prompting
  --no-color         Disable colored terminal output
```

Files are staged as `<name>.part` while transferring and renamed to their
final name only once fully and successfully received, so an interrupted
transfer never appears as a complete file.

## How it works

1. **Advertise** — a zeroconf mDNS service is registered under the Nearby
   Connections WifiLan service type, with an endpoint-info TXT record
   describing this device (name, device type, endpoint ID).
2. **Handshake** — when a phone connects over TCP, both sides run UKEY2: an
   ephemeral ECDH key exchange authenticated by a short PIN the user confirms
   on both ends, from which AES and HMAC keys are derived via HKDF.
3. **Encrypted frames** — all further communication is wrapped in
   SecureMessage frames (AES-256-CBC + HMAC-SHA256) inside the Nearby
   Connections `OfflineFrame` envelope.
4. **Sharing protocol** — inside that, the Nearby Sharing layer negotiates an
   introduction (file metadata), the user accepts or declines, and payload
   bytes stream in over `PayloadTransferFrame` chunks until every file
   completes or the transfer is canceled.

## Source provenance

Every protocol-logic file cites the exact `google/nearby` (and vendored
`google/ukey2`) source paths it was derived from, in its own module
docstring. Summary:

| File | Derived from (in `github.com/google/nearby`) |
|---|---|
| `mdns.py` | `sharing/advertisement.{h,cc}` (endpoint info / TXT record); `connections/implementation/wifi_lan_service_info.{h,cc}` (service instance name envelope); `connections/implementation/mediums/wifi_lan.cc` (`GenerateServiceType`); `connections/implementation/pcp.h`; `connections/implementation/client_proxy.cc` (endpoint ID alphabet); `sharing/common/nearby_share_enums.h` (device type enum) |
| `crypto.py` | `third_party/ukey2/ukey2/src/main/cpp/src/securegcm/ukey2_handshake.cc` (HKDF salts, auth string / next secret derivation); `third_party/ukey2/ukey2/.../securemessage/crypto_ops*.cc` (EC point encoding) |
| `ukey2.py` | `third_party/ukey2/ukey2/src/main/cpp/src/securegcm/ukey2_handshake.cc` (handshake state machine: ClientInit → ServerInit → ClientFinished) |
| `secure_frame.py` | `third_party/ukey2/ukey2/.../securemessage/` (SecureMessage AES-256-CBC + HMAC-SHA256 wrapping) |
| `proto/*.proto` | Copied verbatim from `connections/implementation/proto/offline_wire_formats.proto`, `sharing/proto/wire_format.proto`, `proto/sharing_enums.proto`, and the vendored UKEY2/SecureMessage `.proto` schemas under `third_party/ukey2/ukey2/src/main/proto/` — see per-file table below |
| `server.py` | mDNS registration glue is original to this project (see *Scope and limitations* below); the handshake/connection sequencing follows `connections/implementation/` client-proxy flow |

Anything not spec-mandated (defensive limits, retry/re-registration policy,
the `.part` staging scheme, CLI/UX choices) is original to this project and
documented as such inline, rather than presented as protocol-derived.

Each vendored schema's original location in `github.com/google/nearby`:

| Vendored file | Original path |
|---|---|
| `proto/offline_wire_formats.proto` | `connections/implementation/proto/offline_wire_formats.proto` |
| `proto/wire_format.proto` | `sharing/proto/wire_format.proto` |
| `proto/proto/sharing_enums.proto` | `proto/sharing_enums.proto` |
| `proto/device_to_device_messages.proto` | `third_party/ukey2/ukey2/src/main/proto/device_to_device_messages.proto` |
| `proto/securegcm.proto` | `third_party/ukey2/ukey2/src/main/proto/securegcm.proto` |
| `proto/securemessage.proto` | `third_party/ukey2/ukey2/src/main/proto/securemessage.proto` |
| `proto/ukey.proto` | `third_party/ukey2/ukey2/src/main/proto/ukey.proto` |

One exception is not derived from google/nearby at all, since it has no
equivalent, and is cited to its actual origin instead:

- `framing.py`'s `MAX_FRAME_LENGTH` (a defensive cap on an untrusted socket
  read) shares its exact name and value with
  [grishka/NearDrop](https://github.com/grishka/NearDrop)'s
  `SANE_FRAME_LENGTH` constant (`NearbyShare/NearbyConnection.swift`). Cited
  here as prior art for this specific defensive value only, not as a source
  of protocol logic.

`server.py`'s periodic mDNS re-registration (compensating for this host
having no Bluetooth adapter to trigger a discovery nudge) is a plain
re-advertise on a fixed timer, original to this project.

## Project layout

```
src/quickshare/
  mdns.py         mDNS advertisement: service type, TXT record, endpoint ID
  crypto.py       ECDH, HKDF key derivation, SecureMessage point encoding
  ukey2.py        UKEY2 handshake state machine (server/receiver side)
  secure_frame.py SecureMessage encrypt/decrypt over the handshake keys
  framing.py      4-byte length-prefixed TCP framing
  receive.py      Nearby Sharing protocol state machine, file I/O, consent flow
  server.py       TCP server + mDNS registration glue, CLI entry point logic
  color.py        ANSI terminal color helpers
  cli.py          argparse CLI
  proto/          generated protobuf bindings (see proto/*.proto for sources)

proto/            vendored .proto schemas, copied verbatim from google/nearby
tmp/nearby/       local read-only clone of github.com/google/nearby, used as
                  the reference source for all protocol logic (not imported
                  or shipped — reference only)
```

## Regenerating protobuf bindings

Only needed if you change a `.proto` file. Run the "Generate protobuf
bindings" VS Code task, or equivalently:

```sh
uv run python -m grpc_tools.protoc \
  -I proto \
  --python_out=src/quickshare/proto \
  --pyi_out=src/quickshare/proto \
  proto/device_to_device_messages.proto \
  proto/offline_wire_formats.proto \
  proto/securegcm.proto \
  proto/securemessage.proto \
  proto/ukey.proto \
  proto/wire_format.proto \
  proto/proto/sharing_enums.proto
```

grpc_tools generates some cross-file imports as absolute (`import foo_pb2`)
instead of relative; these need to be hand-fixed to `from . import foo_pb2 as foo__pb2`
after regenerating, or the package won't import.

```
-import securemessage_pb2 as securemessage__pb2
+from . import securemessage_pb2 as securemessage__pb2
```

## Scope and limitations

- **Receive-only.** Sending files from this machine to a phone isn't
  implemented.
- **One transfer at a time.** The server handles a single connection at a
  time, then goes back to advertising.
- **No Bluetooth.** Real Quick Share uses a BLE advertisement to nudge nearby
  devices into scanning for the mDNS service. Without a Bluetooth adapter,
  this receiver instead periodically re-registers its mDNS advertisement as a
  compensating workaround — this is original to this project, not something
  google/nearby's own source does.

## License

Protocol schemas under `proto/` are copied verbatim from
[google/nearby](https://github.com/google/nearby) (Apache-2.0). See
individual `.proto` file headers for their original copyright notices.
