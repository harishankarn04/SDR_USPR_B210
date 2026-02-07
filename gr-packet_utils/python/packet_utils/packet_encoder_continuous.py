
import numpy as np
from gnuradio import gr
import sys
import binascii
from .fec_utils import Scrambler, Hamming74, EOF_SENTINEL

class packet_encoder_continuous(gr.basic_block):
    """
    V4.1 HW-Optimized Continuous Encoder.
    Tailored for B210/Pluto SDRs with longer preambles and optimal timing patterns.
    """
    def __init__(self, preamble=0xAAAAAAAA, sync_word=0xDEADBEEF):
        # We increase vector size to 48 to allow for a much longer hardware preamble
        # 48 bytes gives us plenty of "lead time" for SDR AGC and timing sync
        gr.basic_block.__init__(self, name="packet_encoder_continuous", in_sig=[(np.uint8, 10)], out_sig=[(np.uint8, 48)])
        
        # Preamble: 16 bytes of 0xAA (10101010...) for B210/Pluto
        self.preamble_bytes = [0xAA] * 16
        self.sync_bytes = [(sync_word >> 24) & 0xFF, (sync_word >> 16) & 0xFF, (sync_word >> 8) & 0xFF, sync_word & 0xFF]
        
        self.fec = Hamming74()
        self.scrambler = Scrambler(seed=0x7F)
        
        self.state = "TRAINING"
        self.training_count = 400
        self.end_count = 50
        self.eof_sentinel = list(EOF_SENTINEL)

        # Erasure Coding State
        self.group_id = 0
        self.parity_group_size = 4
        self.data_buffer = [] # Holds payloads for XOR calc
        self.parity_buffer = bytearray(10) # 10 bytes for parity calculation (matches input size)
        self.slot_counter = 0

    def make_packet(self, payload, type_byte=0x01, group_id=0, slot_id=0):
        # Layout (48 bytes):
        # [0:16]  Long Preamble (0xAA...)
        # [16:20] Sync Word
        # [20]    Type (Scrambled) - 1B
        # [21]    GroupID (Scrambled) - 1B
        # [22]    SlotID (Scrambled) - 1B
        # [23:43] Encoded Payload (20 bytes, Scrambled)
        # [43:47] CRC-32 (4 bytes, Scrambled)
        # [47:48] Padding (1 byte)
        
        payload_fec = bytearray()
        for b in payload:
            payload_fec.append(self.fec.encode((b >> 4) & 0x0F))
            payload_fec.append(self.fec.encode(b & 0x0F))
        
        # Calculate CRC-32 of raw payload
        payload_bytes = bytes(payload)
        crc = binascii.crc32(payload_bytes) & 0xFFFFFFFF
        crc_bytes = [(crc >> 24) & 0xFF, (crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF]
        
        # Scramble: Type + Group + Slot + Payload + CRC
        to_scramble = bytearray([type_byte, group_id, slot_id])
        to_scramble.extend(payload_fec)
        to_scramble.extend(crc_bytes)
        
        self.scrambler.reset()
        scrambled = self.scrambler.process(to_scramble)
        
        frame = bytearray(self.preamble_bytes)
        frame.extend(self.sync_bytes)
        frame.extend(scrambled)
        
        # Padding to reach 48 bytes
        while len(frame) < 48:
            frame.append(0x00)
        
        return bytes(frame)

    def general_work(self, input_items, output_items):
        if self.state == "FINISHED":
            self.consume(0, len(input_items[0]))
            return -1

        in_buf = input_items[0]
        out_buf = output_items[0]
        produced = 0
        input_idx = 0
        
        if self.state == "TRAINING":
            while self.training_count > 0 and produced < len(out_buf):
                out_buf[produced, :] = np.frombuffer(self.make_packet([0]*10, 0x00), dtype=np.uint8)
                produced += 1
                self.training_count -= 1
            if self.training_count == 0: 
                self.state = "START"
                self.start_count = 50 # Send multiple START packets for reliability
                
        if self.state == "START" and produced < len(out_buf):
            while self.start_count > 0 and produced < len(out_buf):
                # Start uses GroupID=0, SlotID=0
                out_buf[produced, :] = np.frombuffer(self.make_packet([0xAA]*10, 0x02, 0, 0), dtype=np.uint8)
                produced += 1
                self.start_count -= 1
            if self.start_count == 0:
                self.state = "DATA"
                sys.stderr.write("\n[TX] Training/Start finished. Transmitting data...\n")
                self.group_id = 1 # Start data from Group 1
                self.slot_counter = 0
                self.parity_buffer = bytearray(10) # Input is 10 bytes
            
        if self.state == "DATA":
            while input_idx < len(in_buf) and produced < len(out_buf):
                # Check if this input vector is the EOF sentinel
                if in_buf[input_idx].tolist() == self.eof_sentinel:
                    # Flush remaining parity for the current group
                    if self.slot_counter > 0 and produced < len(out_buf):
                        parity_payload = list(self.parity_buffer)
                        out_buf[produced, :] = np.frombuffer(
                            self.make_packet(parity_payload, 0x05, self.group_id, self.slot_counter),
                            dtype=np.uint8
                        )
                        produced += 1
                    self.state = "END"
                    input_idx += 1
                    break

                # We need to potentially output PARITY packet if slot_counter == N
                if self.slot_counter == self.parity_group_size:
                    # Time to send PARITY
                    parity_payload = list(self.parity_buffer)
                    out_buf[produced, :] = np.frombuffer(
                        self.make_packet(parity_payload, 0x05, self.group_id, self.slot_counter),
                        dtype=np.uint8
                    )
                    produced += 1
                    # Reset for next group
                    self.slot_counter = 0
                    self.group_id = (self.group_id + 1) % 255 # Wrap around
                    if self.group_id == 0: self.group_id = 1 # Avoid 0 (reserved/training)
                    self.parity_buffer = bytearray(10)
                else:
                    # Send DATA packet
                    data = in_buf[input_idx].tolist()

                    # Update Parity
                    for i in range(10):
                        self.parity_buffer[i] ^= data[i]

                    out_buf[produced, :] = np.frombuffer(
                        self.make_packet(data, 0x01, self.group_id, self.slot_counter),
                        dtype=np.uint8
                    )
                    produced += 1
                    input_idx += 1
                    self.slot_counter += 1

        if self.state == "END":
            while self.end_count > 0 and produced < len(out_buf):
                out_buf[produced, :] = np.frombuffer(self.make_packet([0x55]*10, 0x03), dtype=np.uint8)
                produced += 1
                self.end_count -= 1
            if self.end_count == 0:
                sys.stderr.write("\n[TX] End signal sent. Transmission complete.\n")
                self.state = "FINISHED"

        if self.state == "FINISHED":
            # Consume remaining sentinel vectors, produce nothing
            input_idx = len(in_buf)
        
        self.consume(0, input_idx)
        return produced
