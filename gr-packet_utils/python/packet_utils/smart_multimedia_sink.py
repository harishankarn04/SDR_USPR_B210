import numpy as np
from gnuradio import gr
import os
import lzma

class smart_multimedia_sink(gr.basic_block):
    """
    V4.4 Smart Multimedia Sink.
    Automatically detects stream type from source signature:
    - VID\x00 -> Save as .ts (Video)
    - IMG\x00 -> Save as .jpg (Image)
    - FIL\x00 -> Decompress LZMA and Save (General File)
    """
    def __init__(self, filename):
        gr.basic_block.__init__(
            self,
            name="smart_multimedia_sink",
            in_sig=[np.uint8],
            out_sig=None
        )
        self.filename = filename
        self.file = None
        self.mode = "WAITING"
        self.header_buf = b""
        self.lzma_decompressor = None
        self.bytes_written = 0

    def setup_sink(self, sig):
        # Determine actual filename extension
        base, ext = os.path.splitext(self.filename)
        actual_name = self.filename
        
        if sig == b"VID\x00":
            self.mode = "STREAM"
            if not ext: actual_name = base + ".ts"
            print(f"[Smart Sink] Mode: VIDEO. Saving to {actual_name}")
        elif sig == b"IMG\x00":
            self.mode = "STREAM"
            if not ext: actual_name = base + ".jpg"
            print(f"[Smart Sink] Mode: IMAGE. Saving to {actual_name}")
        elif sig == b"FIL\x00":
            self.mode = "LZMA"
            self.lzma_decompressor = lzma.LZMADecompressor()
            print(f"[Smart Sink] Mode: COMPRESSED FILE. Decompressing to {actual_name}")
        else:
            print(f"[Smart Sink] Unknown Signature: {sig}. Defaulting to Raw.")
            self.mode = "STREAM"
        
        self.file = open(actual_name, 'wb')

    def general_work(self, input_items, output_items):
        in_data = input_items[0].tobytes()
        if not in_data: return 0
        
        ptr = 0
        # 1. Read Header
        if self.mode == "WAITING":
            needed = 4 - len(self.header_buf)
            chunk = in_data[:needed]
            self.header_buf += chunk
            ptr += len(chunk)
            if len(self.header_buf) == 4:
                self.setup_sink(self.header_buf)
        
        # 2. Process Data
        payload = in_data[ptr:]
        if payload and self.file:
            if self.mode == "STREAM":
                self.file.write(payload)
                self.bytes_written += len(payload)
            elif self.mode == "LZMA":
                try:
                    decompressed = self.lzma_decompressor.decompress(payload)
                    if decompressed:
                        self.file.write(decompressed)
                        self.bytes_written += len(decompressed)
                except lzma.LZMAError: pass
            
            self.file.flush()
            if self.bytes_written % (1024*100) < len(payload):
                print(f"[Smart Sink] Progress: {self.bytes_written/1024:.1f} KB")

        self.consume(0, len(in_data))
        return 0

    def stop(self):
        if self.file:
            self.file.close()
            print(f"[Smart Sink] Finished. Total written: {self.bytes_written} bytes.")
        return True
