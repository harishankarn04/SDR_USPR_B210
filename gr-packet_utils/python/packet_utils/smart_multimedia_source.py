import numpy as np
from gnuradio import gr
import os
import subprocess
import io
import lzma
from PIL import Image
import mimetypes

class smart_multimedia_source(gr.basic_block):
    """
    V4.4 Smart Multimedia Source.
    Auto-detects file type and applies the best robust compression:
    - Video -> HEVC (H.265) + AAC
    - Image -> JPEG
    - File  -> LZMA (XZ)
    """
    def __init__(self, filename, repeat=False, video_bitrate="500k", image_quality=75):
        gr.basic_block.__init__(
            self,
            name="smart_multimedia_source",
            in_sig=None,
            out_sig=[np.uint8]
        )
        self.filename = filename
        self.repeat = repeat
        self.data = b""
        self.ptr = 0
        
        if not os.path.exists(filename):
            print(f"[Smart Source] Error: {filename} not found.")
            return

        mime, _ = mimetypes.guess_type(filename)
        
        # 1. Detect and Process
        if mime and mime.startswith('video'):
            self.process_video(filename, video_bitrate)
        elif mime and mime.startswith('image'):
            self.process_image(filename, image_quality)
        else:
            self.process_general_file(filename)

        # 2. Finalize and Pad
        if self.data:
            # Align to 10 bytes for the encoder
            align_pad = (10 - (len(self.data) % 10)) % 10
            self.data += b"\x00" * align_pad
            
            # Add Large Flush Tail (4000 bytes)
            # Smart Source flows through more buffers, so we add extra "lead-out"
            self.data += b"\x00" * 4000
            print(f"[Smart Source] Final Payload with Flush Tail: {len(self.data)} bytes (Ready for SDR)")

    def process_video(self, filename, bitrate):
        print(f"[Smart Source] Detected VIDEO. Transcoding to HEVC @ {bitrate}...")
        cmd = [
            'ffmpeg', '-i', filename, '-y',
            '-c:v', 'libx265', '-preset', 'ultrafast', '-b:v', bitrate,
            '-c:a', 'aac', '-b:a', '64k',
            '-f', 'mpegts', 'pipe:1'
        ]
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            transcoded, err = process.communicate()
            if process.returncode == 0:
                # Signature: 'VID\x00'
                self.data = b"VID\x00" + transcoded
            else:
                print(f"[Smart Source] FFmpeg Error: {err.decode()}")
        except Exception as e:
            print(f"[Smart Source] Video Failed: {e}")

    def process_image(self, filename, quality):
        print(f"[Smart Source] Detected IMAGE. Transcoding to JPEG (Q={quality})...")
        try:
            img = Image.open(filename)
            if img.mode in ("RGBA", "P"): img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality)
            # Signature: 'IMG\x00'
            self.data = b"IMG\x00" + buf.getvalue()
        except Exception as e:
            print(f"[Smart Source] Image Failed: {e}")

    def process_general_file(self, filename):
        print(f"[Smart Source] Detected GENERAL FILE. Compressing with LZMA...")
        try:
            with open(filename, 'rb') as f:
                raw = f.read()
            compressed = lzma.compress(raw)
            # Signature: 'FIL\x00'
            self.data = b"FIL\x00" + compressed
        except Exception as e:
            print(f"[Smart Source] File Failed: {e}")

    def general_work(self, input_items, output_items):
        out = output_items[0]
        n = len(out)
        remaining = len(self.data) - self.ptr
        if remaining <= 0:
            if self.repeat: self.ptr = 0; remaining = len(self.data)
            else: return -1
        n_out = min(n, remaining)
        out[:n_out] = np.frombuffer(self.data[self.ptr : self.ptr + n_out], dtype=np.uint8)
        self.ptr += n_out
        return n_out
