# SDR USPR B210 — Packet-Based Multimedia Transceiver

GNURadio 3.10 custom blocks for transmitting multimedia (video, images, files) over SDR using GFSK modulation with FEC, scrambling, and erasure coding.

Designed for USRP B210 and Pluto SDRs.

## Blocks

| Block                            | Description                                                                  |
| -------------------------------- | ---------------------------------------------------------------------------- |
| **Smart Source**           | Auto-detects file type and compresses (video→HEVC, image→JPEG, file→LZMA) |
| **Smart Sink**             | Receives and reconstructs the original file from the stream                  |
| **Packet TX (Continuous)** | Encodes bytes into framed packets and GFSK-modulates to complex samples      |
| **Packet RX (Continuous)** | GFSK-demodulates, finds sync, decodes packets with FEC and erasure recovery  |

## Dependencies

- GNURadio 3.10+
- Python packages: `pip install -r requirements.txt`
- `ffmpeg` on PATH (for video transcoding)

## Installation

These are pure Python blocks — no CMake or C++ build required.
Copy the Python modules and GRC block definitions into your GNURadio install paths.

### macOS (Conda / Radioconda)

On macOS, GNURadio is typically installed via Conda or Radioconda since Homebrew's Boost can conflict with GNURadio's dependencies.

```bash
# Activate your conda environment that has gnuradio
conda activate base   # or whichever env has gnuradio

# Install Python dependencies
pip install -r requirements.txt

# Copy blocks into the conda environment
GR_CONDA=$(python3 -c "import gnuradio, os; print(os.path.dirname(gnuradio.__path__[0]))") && echo $GR_CONDA
cp -r gr-packet_utils/python/packet_utils $GR_CONDA/gnuradio/packet_utils

# Copy GRC block definitions
cp gr-packet_utils/grc/*.yml $CONDA_PREFIX/share/gnuradio/grc/blocks/
```

### Linux (system install)

On Linux, GNURadio is usually installed system-wide via package manager (`apt`, `dnf`, etc.).

```bash
# Install GNURadio if not already installed
# Ubuntu/Debian:
sudo apt install gnuradio

# Install Python dependencies
pip install -r requirements.txt

# Find your GNURadio Python path
GR_PYTHON=$(python3 -c "import gnuradio, os; print(os.path.dirname(gnuradio.__path__[0]))") && echo $GR_PYTHON
GR_DATA=$(python3 -c "from gnuradio import gr; import os; print(os.path.join(gr.prefix(), 'share', 'gnuradio', 'grc', 'blocks'))") && echo $GR_DATA

# Verify paths exist
test -d "$GR_PYTHON/gnuradio" && echo "Python path OK" || { echo "ERROR: $GR_PYTHON/gnuradio not found"; exit 1; }
test -d "$GR_DATA" && echo "GRC path OK" || { echo "ERROR: $GR_DATA not found"; exit 1; }

# Copy blocks
sudo cp -r gr-packet_utils/python/packet_utils $GR_PYTHON/gnuradio/packet_utils

# Copy GRC block definitions
sudo cp gr-packet_utils/grc/*.yml $GR_DATA/
```

<!-- Or if you know your prefix (commonly `/usr` or `/usr/local`):

```bash
sudo cp -r gr-packet_utils/python/packet_utils /usr/lib/python3/dist-packages/gnuradio/packet_utils

sudo cp gr-packet_utils/grc/*.yml /usr/share/gnuradio/grc/blocks/
``` -->

### Verify installation

After copying, restart GNURadio Companion. The blocks appear under the **[packet_utils]** category.

```bash
# Quick check that the module loads
python -c "from gnuradio import packet_utils; print('OK')"
```

## Protocol Overview

```
Smart Source → Packet TX → [SDR / Channel] → Packet RX → Smart Sink
```

- **Modulation**: GFSK (configurable samples/symbol, sensitivity, BT)
- **Packet format** (48 bytes): 16B preamble + 4B sync word + scrambled payload with Hamming(7,4) FEC + CRC-32
- **Erasure coding**: Every 4 data packets are followed by 1 XOR parity packet, allowing recovery of any single lost packet per group
- **Training sequence**: 400 idle packets at start for AGC and timing lock

## Usage Notes

- **Output filenames**: When configuring the Smart Sink, use `output` in the filename (e.g. `1080p_output.mp4`). Output files with `output` in the name are git-ignored to keep the repo clean.

## Flowgraph

`Openlab.grc` contains a loopback test using a channel model (noise=0.2). The UHD B210 source/sink blocks are included but disabled — enable them for over-the-air transmission.
