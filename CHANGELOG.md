# Project Reference — SDR USRP B210 Packet Multimedia Transceiver

## What This Project Does

Transmits multimedia files (video, images, any file) over Software Defined Radio using custom GNU Radio 3.10 blocks. Uses GFSK modulation with error correction, scrambling, and erasure coding. Designed for USRP B210 and Pluto SDRs.

## Full Signal Chain

```
Smart Source → Throttle → [S2V] → Encoder → [V2S] → GFSK Mod → [SDR/Channel] → GFSK Demod → Bit Packer → Decoder → Smart Sink
```

- S2V = stream_to_vector (groups 10 bytes into vectors)
- V2S = vector_to_stream (unpacks 48-byte packet vectors back to stream)
- In loopback mode, the SDR is replaced by a channel model (simulated noise)

## File Structure

| File | Purpose |
|---|---|
| `Openlab.py` | GNU Radio flowgraph (auto-generated from `Openlab.grc`) |
| `Openlab.grc` | GRC flowgraph file (open in GNU Radio Companion) |
| `gr-packet_utils/python/packet_utils/` | All custom block source code |
| `fec_utils.py` | Scrambler, Hamming(7,4) FEC, CRC-32, EOF sentinel constant |
| `smart_multimedia_source.py` | File reader + compression (source block) |
| `smart_multimedia_sink.py` | File writer + decompression (sink block) |
| `packet_encoder_continuous.py` | Byte-to-packet framing (core TX logic) |
| `packet_decoder_continuous.py` | Packet-to-byte deframing (core RX logic) |
| `packet_tx_continuous.py` | Hierarchical TX: encoder + GFSK modulator |
| `packet_rx_continuous.py` | Hierarchical RX: GFSK demodulator + decoder |

## Smart Source — How Files Are Prepared

- Auto-detects file type using MIME
- **Video** → transcodes to HEVC (H.265) + AAC via ffmpeg, outputs MPEG-TS container
- **Image** → compresses to JPEG via Pillow
- **Any other file** → compresses with LZMA (XZ)
- Prepends a 4-byte signature: `VID\x00`, `IMG\x00`, or `FIL\x00`
- Pads to 10-byte alignment (encoder needs 10-byte input vectors)
- Appends 4000-byte flush tail (zeros) — gives the pipeline time to drain
- Appends 50 copies of EOF sentinel (`0xDEADBEEFCAFEBABEF00D`) — tells the encoder to stop
- Returns `-1` (WORK_DONE) when all bytes are sent

## Smart Sink — How Files Are Reconstructed

- Reads first 4 bytes to detect signature
- `VID\x00` or `IMG\x00` → writes raw stream directly to file
- `FIL\x00` → decompresses LZMA on the fly
- `stop()` method closes the file when flowgraph finishes

## Packet Format — 48 Bytes Per Packet

```
[0:16]   Preamble — 16 bytes of 0xAA (alternating 10101010... for clock recovery)
[16:20]  Sync Word — 0xDEADBEEF (4 bytes, used by decoder to find packet start)
[20:47]  Scrambled payload (27 bytes):
           [0]    Type byte
           [1]    Group ID
           [2]    Slot ID
           [3:23] FEC-encoded payload (20 bytes = 10 data bytes x Hamming 7,4)
           [23:27] CRC-32 of the original 10 data bytes
[47]     Padding byte
```

## Packet Types

| Type | Hex | Purpose | Count |
|---|---|---|---|
| TRAINING | `0x00` | Idle packets for AGC/timing lock | 400 packets |
| START | `0x02` | Signals receiver that data is about to begin | 50 packets |
| DATA | `0x01` | Carries 10 bytes of actual file data | variable |
| PARITY | `0x05` | XOR of previous 4 data packets (erasure coding) | 1 per 4 data |
| END | `0x03` | Signals transmission is complete | 50 packets |

## Encoder State Machine

```
TRAINING (400 packets) --> START (50 packets) --> DATA --> END (50 packets) --> FINISHED
```

- TRAINING: sends idle packets so the receiver can lock AGC and timing
- START: tells receiver to begin accepting data
- DATA: processes 10-byte input vectors into 48-byte framed packets
  - Every 4 data packets, sends 1 parity packet (erasure coding group)
  - When EOF sentinel is detected, flushes remaining parity, transitions to END
- END: sends 50 end-of-stream packets for reliability
- FINISHED: consumes remaining input, produces nothing

## Decoder Pipeline

1. **Soft sync detection** (`find_sync_soft`): slides a bit-level window over input, matches against `0xDEADBEEF` allowing up to 2 bit flips (tolerates noise)
2. **Bit-shift correction** (`get_shifted_data`): if sync was found at a non-byte-aligned offset, shifts the data to realign
3. **Descramble**: reverses the LFSR scrambler (same seed `0x7F`)
4. **FEC decode**: Hamming(7,4) on each nibble pair, recovers 10 original bytes
5. **CRC-32 check**: verifies integrity, drops corrupted packets
6. **Erasure coding**: buffers packets by group ID, reconstructs 1 missing packet per group of 4 using XOR parity
7. **END detection**: when END packet arrives, flushes remaining data, sets `finished=True`, returns `-1`

## FEC — Forward Error Correction

### Scrambler (fec_utils.py)
- Additive scrambler using LFSR polynomial: **x^7 + x^4 + 1**
- Seed: `0x7F`
- XORs each byte with pseudo-random sequence — whitens the spectrum
- Reset before each packet so encoder and decoder stay in sync
- **Why**: prevents long runs of 0s or 1s that confuse clock recovery

### Hamming(7,4) (fec_utils.py)
- Encodes each 4-bit nibble into 7 bits (rate 4/7, about 57%)
- Can correct any single-bit error per codeword
- Each data byte becomes 2 nibbles, 2 codewords, 2 bytes (doubles the payload size: 10 to 20 bytes)
- Decode uses a 128-entry lookup table (precomputed for all possible 7-bit values including 1-bit errors)
- **Why**: corrects bit errors introduced by channel noise

### CRC-32 (fec_utils.py)
- Standard CRC-32 (same as zip/ethernet)
- Computed on the original 10 data bytes before FEC encoding
- 4 bytes appended to each packet, scrambled along with the payload
- Decoder recomputes and compares — rejects packets where CRC doesn't match
- **Why**: detects multi-bit errors that Hamming can't correct

### Erasure Coding (packet_encoder/decoder)
- Every 4 data packets form a group (same Group ID, Slot IDs 0-3)
- A 5th parity packet (Slot ID 4, Type `0x05`) contains the byte-wise XOR of all 4 data payloads
- If any 1 packet in the group is lost (CRC fail / not received), it can be reconstructed: `missing = parity XOR all_other_data_packets`
- If 2+ packets are lost, reconstruction fails — remaining packets are output with gaps
- **Why**: recovers from single packet losses without retransmission (important for one-way radio links)

## Modulation — GFSK

- **Gaussian Frequency Shift Keying** via GNU Radio's `digital.gfsk_mod` / `digital.gfsk_demod`
- Parameters: `samples_per_symbol=2`, `sensitivity=1.0`, `bt=0.35`
- BT (bandwidth-time product) of 0.35 = Bluetooth-like Gaussian filter
- Input: bytes, Output: complex IQ samples (ready for SDR)
- Demod uses Mueller and Muller clock recovery (`gain_mu=0.175`, `mu=0.5`)
- After demod, `pack_k_bits_bb(8)` reassembles bits into bytes

## TX Hierarchical Block (packet_tx_continuous.py)

```
bytes_in --> stream_to_vector(10) --> packet_encoder --> vector_to_stream(48) --> GFSK mod --> complex_out
```

- `hier_block2` = a reusable sub-flowgraph in GNU Radio
- S2V groups every 10 input bytes into one vector for the encoder
- V2S unpacks each 48-byte packet vector back to a byte stream for the modulator

## RX Hierarchical Block (packet_rx_continuous.py)

```
complex_in --> GFSK demod --> pack_k_bits(8) --> packet_decoder --> bytes_out
```

- GFSK demod outputs individual bits
- `pack_k_bits_bb(8)` packs 8 bits into 1 byte
- Decoder searches for sync, decodes packets, outputs recovered data bytes

## EOF / Auto-Stop Mechanism

- Source appends 50 copies of `EOF_SENTINEL` (10-byte pattern `0xDEADBEEFCAFEBABEF00D`) after the flush tail
- Encoder checks each input vector against the sentinel — on match, flushes parity, sends 50 END packets
- Decoder sets `finished=True` on first END packet, returns `-1` on next call, stops the pipeline
- Sink's `stop()` closes the output file
- `Openlab.py` runs a monitor thread: `tb.wait()` then `qapp.quit()` then window closes automatically

## Loopback Test (Openlab.py / Openlab.grc)

- Source reads a video file, TX encodes + modulates, passes through a channel model (noise_voltage=0.2), RX demodulates + decodes, Sink writes output
- No real SDR hardware needed — channel model simulates noise
- Sample rate: 1 MHz
- The GRC file has UHD B210 source/sink blocks (disabled) — enable them for over-the-air testing

## Installation

- Pure Python — no C++ or CMake needed
- Copy `gr-packet_utils/python/packet_utils/` into your GNU Radio's `gnuradio/` package directory
- Copy `gr-packet_utils/grc/*.yml` into GNU Radio's GRC blocks directory
- Python deps: `pip install -r requirements.txt`
- Needs `ffmpeg` on PATH for video transcoding

---

## Changes Log

### 2026-02-06

- **END packet protocol**: source sends EOF sentinel, encoder sends END packets, decoder auto-stops, window auto-closes
- **Decoder status line**: replaced `.SSE` character spam with single updating line showing all counters
- **README**: removed hardcoded Linux paths, added path verification, removed Windows section
