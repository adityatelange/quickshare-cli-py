# Quick Share CLI (for Linux)

A minimal, dependency-light Python CLI for **Google Quick Share** (formerly
Nearby Share) on Linux: send and receive. Run it on a laptop or desktop with
no Bluetooth adapter, and Android phones on the same network can send files
to it, or receive files from it, the same way they would with another
Android device or a ChromeOS/Windows machine.

One connection at a time (though a single transfer can bundle multiple
files, e.g. `quickshare send Downloads/*.pdf`), no GUI, built for a Linux
desktop or headless box that just needs to shuttle files to or from a phone.

<video src="https://github.com/user-attachments/assets/1353b8a4-a15f-4721-9277-680a5db0ffa1"></video>

## Requirements

- Linux, Python 3.10
- [uv](https://docs.astral.sh/uv/) for dependency management
- A network interface that can reach the sending phone (Wi-Fi or wired LAN,
  no Bluetooth needed)

## Installation

To just install the `quickshare` command, pick one:

```bash
# uv (recommended)
uv tool install git+https://github.com/adityatelange/quickshare-cli-py

# pipx
pipx install git+https://github.com/adityatelange/quickshare-cli-py

# pip
pip install git+https://github.com/adityatelange/quickshare-cli-py
```

Any of these puts a `quickshare` command on your `PATH`.

See [Usage](#usage) for how to run it, and [Setup](#setup) if you want to work on the code instead of just installing the command.

## Features

**Receiving**
- Advertises over mDNS (`_FC9F5ED42C8A._tcp.local.`) so phones on the same
  LAN/Wi-Fi discover this machine as a Quick Share target
- PIN-verified consent prompt before accepting a transfer (or `--yes` to
  auto-accept)
- Cancel a transfer mid-flight (Ctrl+C on the receiver, or from the sender);
  either way the partial file is discarded, never left under its real name
- Stable device identity across restarts (derived from hostname, not MAC,
  no more re-pairing every time you restart the receiver)

**Sending**
- Browses mDNS for nearby Quick Share receivers and shows an interactive
  numbered picker, or connect directly with `--target host:port`
- Sends one or more files in a single transfer, with a PIN shown for the
  same confirmation-code check as receiving
- Interoperates with real Android/ChromeOS/Windows Quick Share receivers,
  not just this project's own receiver

**Both directions**
- Full UKEY2 handshake (ECDH P-256 + HKDF-SHA256) and SecureMessage frame
  encryption (AES-256-CBC + HMAC-SHA256)
- Live progress bar with percentage (and transfer speed, when receiving)
- Colored terminal output (`--no-color` to disable)

## Setup

To work on the code instead:

```bash
uv sync
```

This installs runtime dependencies (`zeroconf`, `protobuf`, `cryptography`,
`ifaddr`) and the dev-only `grpcio-tools`, used solely to regenerate the
protobuf bindings under `src/quickshare/proto/` (already checked in, you
don't need to regenerate them to just run the receiver or sender).

## Usage

Examples below use `uv run quickshare ...` (running from a source checkout,
see [Setup](#setup)). If you installed via `uv tool`/`pipx`/`pip`, drop the
`uv run` prefix and just run `quickshare ...`.

### Receiving

```bash
uv run quickshare receive
```

The phone must be on the same network and have Quick Share's visibility set
to allow "everyone" (or your account/contacts, depending on Android version).
When a transfer comes in you'll see a PIN to confirm on both devices, then a
progress bar as the file downloads.

```bash
uv run quickshare receive [-o OUTPUT_DIR] [-n NAME] [-i IFACE] [--yes] [--no-color]
                          [--debug] [--debug-trace]

  -o, --output-dir   Directory to save received files into (default: current directory)
  -n, --name         Device name to advertise (default: hostname)
  -i, --iface        Network interface to advertise on, e.g. enp6s0 (default: auto-detect)
  --yes              Auto-accept incoming transfers without prompting
  --no-color         Disable colored terminal output
  --debug            Log the protocol frame sequence to stderr
  --debug-trace      Even more verbose: per-chunk frames and key material on HMAC failure
```

Files are staged as `<name>.part` while transferring and renamed to their
final name only once fully and successfully received, so an interrupted
transfer never appears as a complete file.

### Sending

```bash
uv run quickshare send photo.jpg document.pdf
```

Browses for nearby Quick Share receivers for a few seconds, shows a numbered
list, and asks which one to send to. Confirm the PIN shown here matches the
one shown on the receiving device, then accept the transfer there.

```bash
uv run quickshare send PATH [PATH ...] [-n NAME] [-i IFACE] [-t HOST:PORT] [--no-color]
                       [--debug] [--debug-trace]

  -n, --name         Device name to advertise as sender (default: hostname)
  -i, --iface        Network interface to use for discovery, e.g. enp6s0 (default: auto-detect)
  -t, --target       Connect directly to host:port instead of discovering (skips the picker)
  --no-color         Disable colored terminal output
  --debug            Log the protocol frame sequence to stderr
  --debug-trace      Even more verbose: per-chunk frames and key material on HMAC failure
```

### Debug logging

Quick Share failures tend to look like "the phone hung up and said nothing".
`--debug` prints the protocol frame sequence to stderr so you can see how far
the exchange actually got, timestamped and tagged with the module that
emitted each line.

`--debug` also un-silences the two places where problems are otherwise
swallowed on purpose: mDNS advertisements that fail to parse (skipped
silently during discovery so one bad peer can't disrupt the rest, which
makes "my phone never appears in the list" hard to diagnose otherwise), and
the traceback behind a `Transfer failed:` / `Send failed:` message.

`--debug-trace` adds every wire frame, SecureMessage sequence number, and
payload chunk. It is genuinely verbose (a few lines per 64 KiB of file), so
reach for it when a transfer stalls partway rather than as a default.

> **Note:** `--debug-trace` prints raw key material if HMAC verification
> fails, since diagnosing a key-derivation mismatch requires comparing the
> bytes on both ends. Don't paste that output into a public bug report.
> Plain `--debug` never prints key material or file contents.

Both levels can also be set via the environment, which is handy when
`quickshare` is invoked by a script or another tool:

```bash
QUICKSHARE_DEBUG=1     quickshare receive   # same as --debug
QUICKSHARE_DEBUG=trace quickshare receive   # same as --debug-trace
```

An explicit flag always wins over the environment variable. All debug output
goes to stderr, so it never mixes into anything you pipe on stdout.

### File manager integration (Nemo)

On Cinnamon/Linux Mint, Nemo supports custom right-click actions. Drop these
into `~/.local/share/nemo/actions/` to get "Quick Share Send" and "Quick
Share Receive" entries in the context menu:

`~/.local/share/nemo/actions/quickshare_send.nemo_action`:

```ini
[Nemo Action]
Name=Quick Share Send
Comment=Share file via QuickShare
Exec=gnome-terminal -- bash -c 'quickshare send "$@"; echo; read -p "Press Enter to close..."' _ %F
Selection=Any
Extensions=any;
```

`~/.local/share/nemo/actions/quickshare_receive.nemo_action`:

```ini
[Nemo Action]
Name=Quick Share Receive
Comment=Receive files via Quick Share
Exec=gnome-terminal -- bash -c 'quickshare receive -o "$1"; echo; read -p "Press Enter to close..."' _ %P
Selection=Any
Extensions=any;
```

"Send" runs on the selected file(s); "Receive" runs on the current folder and
saves incoming files there. Both keep the terminal open after the transfer so
you can see the result before it closes.

## How it works

1. **Discover:** the receiver registers a zeroconf mDNS service under the
   Nearby Connections WifiLan service type, with an endpoint-info TXT record
   describing itself (name, device type, endpoint ID); the sender browses for
   that same service type and decodes the instance name/TXT record back into
   a device to connect to.
2. **Handshake:** over TCP, both sides run UKEY2 with opposite roles
   (receiver = server, sender = client): an ephemeral ECDH key exchange
   authenticated by a short PIN the user confirms on both ends, from which
   AES and HMAC keys are derived via HKDF.
3. **Encrypted frames:** all further communication is wrapped in
   SecureMessage frames (AES-256-CBC + HMAC-SHA256) inside the Nearby
   Connections `OfflineFrame` envelope.
4. **Sharing protocol:** inside that, the Nearby Sharing layer runs a
   paired-key verification round (this project has no contact/certificate
   store, so it always reports "unable to verify" rather than skipping PIN
   confirmation), then the sender offers files via an introduction frame, the
   receiver accepts or declines, and payload bytes stream from sender to
   receiver over `PayloadTransferFrame` chunks until every file completes or
   the transfer is canceled.

## Source provenance

Every protocol-logic file cites the exact `google/nearby` (and vendored
`google/ukey2`) source paths it was derived from, in its own module
docstring. Summary:

| File | Derived from (in `github.com/google/nearby`) |
|---|---|
| `mdns.py` | `sharing/advertisement.{h,cc}` (endpoint info / TXT record); `connections/implementation/wifi_lan_service_info.{h,cc}` (service instance name envelope); `connections/implementation/mediums/wifi_lan.cc` (`GenerateServiceType`); `connections/implementation/pcp.h`; `connections/implementation/client_proxy.cc` (endpoint ID alphabet); `sharing/common/nearby_share_enums.h` (device type enum) |
| `discover.py` | Same files as `mdns.py`, parse direction (`WifiLanServiceInfo::WifiLanServiceInfo(const NsdServiceInfo&)` in `wifi_lan_service_info.cc`; `sharing::Advertisement::FromEndpointInfo` in `sharing/advertisement.{h,cc}`) |
| `crypto.py` | `third_party/ukey2/ukey2/src/main/cpp/src/securegcm/ukey2_handshake.cc` (HKDF salts, auth string / next secret derivation, symmetric across both handshake roles); `third_party/ukey2/ukey2/.../securemessage/crypto_ops*.cc` (EC point encoding) |
| `ukey2.py` | `third_party/ukey2/ukey2/src/main/cpp/src/securegcm/ukey2_handshake.cc` (handshake state machine for both roles: ClientInit → ServerInit → ClientFinished, including the client's commit-before-send cipher-commitment construction) |
| `secure_frame.py` | `third_party/ukey2/ukey2/.../securemessage/` (SecureMessage AES-256-CBC + HMAC-SHA256 wrapping) |
| `proto/*.proto` | Copied verbatim from `connections/implementation/proto/offline_wire_formats.proto`, `sharing/proto/wire_format.proto`, `proto/sharing_enums.proto`, and the vendored UKEY2/SecureMessage `.proto` schemas |
| `server.py` | mDNS registration glue is original to this project (see *Scope and limitations* below); the handshake/connection sequencing follows `connections/implementation/` client-proxy flow |
| `send.py` | `connections/implementation/base_pcp_handler.cc` and `offline_frames.cc` (ConnectionRequest/ConnectionResponse construction, client-role sequencing); `sharing/outgoing_share_session.cc` (introduction frame construction, payload send loop); `sharing/paired_key_verification_runner.cc` (paired-key frame ordering); `connections/implementation/payload_manager.cc` (64 KiB chunk size, empty-chunk `LAST_CHUNK` termination) |

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

```bash
src/quickshare/
  mdns.py         mDNS advertisement: service type, TXT record, endpoint ID
  discover.py     mDNS browsing: parses discovered services back into devices
  crypto.py       ECDH, HKDF key derivation, SecureMessage point encoding
  ukey2.py        UKEY2 handshake state machine (both server and client roles)
  secure_frame.py SecureMessage encrypt/decrypt over the handshake keys
  framing.py      4-byte length-prefixed TCP framing
  receive.py      Nearby Sharing protocol state machine, file I/O, consent flow
  send.py         Sender-side connect/handshake/introduction/payload-send flow
  server.py       TCP server + mDNS registration glue, receive CLI entry point
  color.py        ANSI terminal color helpers
  debug.py        opt-in protocol logging behind --debug/--debug-trace
  cli.py          argparse CLI
  proto/          generated protobuf bindings (see proto/*.proto for sources)

proto/            vendored .proto schemas, copied verbatim from google/nearby
```

## Regenerating protobuf bindings

Only needed if you change a `.proto` file. Run the "Generate protobuf
bindings" VS Code task, or equivalently:

```bash
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

```diff
-import securemessage_pb2 as securemessage__pb2
+from . import securemessage_pb2 as securemessage__pb2
```

## Scope and limitations

- **One transfer at a time**, in either direction. The receiver handles a
  single connection at a time, then goes back to advertising; the sender
  connects to exactly one target per invocation.
- **No paired-device/contacts trust.** This project has no certificate store,
  so paired-key verification always reports "unable to verify" on both sides,
  every transfer requires the PIN confirmation, there's no silent
  already-trusted fast path.
- **No Bluetooth.** Real Quick Share uses a BLE advertisement to nudge nearby
  devices into scanning for the mDNS service. Without a Bluetooth adapter,
  the receiver instead periodically re-registers its mDNS advertisement as a
  compensating workaround, this is original to this project, not something
  google/nearby's own source does. The sender has no equivalent workaround to
  make (it isn't advertising anything); it just browses whenever invoked.

## License

Protocol schemas under `proto/` are copied verbatim from
[google/nearby](https://github.com/google/nearby) (Apache-2.0). See
individual `.proto` file headers for their original copyright notices.
