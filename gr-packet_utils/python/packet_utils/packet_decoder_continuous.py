
import numpy as np
from gnuradio import gr
import sys
import binascii
from .fec_utils import Scrambler, Hamming74

class packet_decoder_continuous(gr.basic_block):
    """
    V4.0 Really Robust Continuous Decoder.
    Supports Descrambling and CRC-32 verification.
    """
    def __init__(self, sync_word=0xDEADBEEF):
        gr.basic_block.__init__(
            self,
            name="packet_decoder_continuous",
            in_sig=[np.uint8],
            out_sig=[np.uint8]
        )
        self.sync_bytes = bytes([
            (sync_word >> 24) & 0xFF, (sync_word >> 16) & 0xFF,
            (sync_word >> 8) & 0xFF, sync_word & 0xFF
        ])
        
        self.fec = Hamming74()
        self.descrambler = Scrambler(seed=0x7F)
            
        self.active = False
        self.current_shift = 0

        # Erasure Coding Buffer
        self.current_group_id = -1
        self.group_buffer = {} # SlotID -> 10-byte Payload
        self.parity_group_size = 4

        self.finished = False

        # Status counters
        self.training_rx = 0
        self.start_rx = 0
        self.data_rx = 0
        self.parity_rx = 0
        self.recovered_rx = 0
        self.crc_fail = 0

        # Pre-compute bit representations of sync bytes for faster bit-flip matching
        self.sync_bits = np.unpackbits(np.frombuffer(self.sync_bytes, dtype=np.uint8))

    def get_shifted_data(self, data_bytes, shift):
        if shift == 0: return data_bytes
        bits = np.unpackbits(np.frombuffer(data_bytes, dtype=np.uint8))
        shifted_bits = bits[shift:]
        rem = len(shifted_bits) % 8
        if rem != 0: shifted_bits = shifted_bits[:-rem]
        return np.packbits(shifted_bits).tobytes()

    def _print_status(self):
        state = "RECEIVING" if self.active else "TRAINING"
        line = (f"\r[RX] {state} | train: {self.training_rx}  start: {self.start_rx}  "
                f"data: {self.data_rx}  parity: {self.parity_rx}  "
                f"recovered: {self.recovered_rx}  crc_fail: {self.crc_fail}  ")
        sys.stderr.write(line)
        sys.stderr.flush()

    def flush_group(self, output_items, produced):
        """Reconstructs missing packet if possible and flushes buffer."""
        added = 0
        missing_slots = []
        
        # Check slots 0..N-1 (Data slots)
        for i in range(self.parity_group_size):
            if i not in self.group_buffer:
                missing_slots.append(i)
        
        if len(missing_slots) == 0:
            # All data present. Flush.
            for i in range(self.parity_group_size):
                output_items[produced + added : produced + added + 10] = self.group_buffer[i]
                added += 10 # 10 bytes per packet
        
        elif len(missing_slots) == 1 and self.parity_group_size in self.group_buffer:
            # One missing, Parity (Slot N) present. Reconstruct!
            missing_idx = missing_slots[0]
            
            # Start with Parity
            recovered = bytearray(self.group_buffer[self.parity_group_size])
            
            # XOR with all present data slots
            for i in range(self.parity_group_size):
                if i != missing_idx and i in self.group_buffer:
                    data = self.group_buffer[i]
                    for b in range(10):
                        recovered[b] ^= data[b]
            
            # Store recovered
            self.group_buffer[missing_idx] = recovered
            self.recovered_rx += 1
            
            # Flush all
            for i in range(self.parity_group_size):
                output_items[produced + added : produced + added + 10] = self.group_buffer[i]
                added += 10
        else:
            # Too many missing or no parity. Output what we have? 
            # For strict stream integrity, we should output zeros for missing?
            # Or just output gaps? 
            # User request: "Reconstruction". If failed, maybe drop or output whatever.
            # Let's output what we have to keep flow moving, but it will be gaps.
             for i in range(self.parity_group_size):
                if i in self.group_buffer:
                    output_items[produced + added : produced + added + 10] = self.group_buffer[i]
                    added += 10
        
        self.group_buffer.clear()
        return added

    def process_packet(self, data, sync_idx, output_items, produced):
        # Layout: [Sync(4)] [Scrambled(27)] [Padding(1)]
        # Scrambled: Type(1) + Group(1) + Slot(1) + Payload(20) + CRC(4) = 27 bytes
        required = sync_idx + 4 + 27
        
        if len(data) >= required:
            scrambled_part = data[sync_idx + 4 : sync_idx + 31]
            
            # Descramble
            self.descrambler.reset()
            descrambled = self.descrambler.process(scrambled_part)
            
            type_byte = descrambled[0]
            group_id = descrambled[1]
            slot_id = descrambled[2]
            
            payload_fec = descrambled[3:23]
            recv_crc = (descrambled[23] << 24) | (descrambled[24] << 16) | \
                       (descrambled[25] << 8) | descrambled[26]
            
            # FEC Decode
            decoded = bytearray()
            for i in range(10):
                n1 = self.fec.decode(payload_fec[i*2])
                n2 = self.fec.decode(payload_fec[i*2+1])
                decoded.append((n1 << 4) | n2)
            
            # CRC-32 Check
            calc_crc = binascii.crc32(decoded) & 0xFFFFFFFF
            
            if calc_crc == recv_crc:
                total_produced = 0
                
                # Handle Signals
                if type_byte == 0x00: # TRAINING
                    self.training_rx += 1
                    self._print_status()
                    return required, 0
                if type_byte == 0x02: # START
                    self.start_rx += 1
                    self.active = True
                    self.current_group_id = -1
                    self.group_buffer.clear()
                    self._print_status()
                    return required, 0
                if type_byte == 0x03: # END
                    self._print_status()
                    sys.stderr.write("\n[RX] Stream ended.\n")
                    self.active = False
                    self.finished = True
                    # Flush pending
                    total_produced += self.flush_group(output_items, produced)
                    return required, total_produced
                
                # Handle Data/Parity
                if self.active and (type_byte == 0x01 or type_byte == 0x05):
                    if type_byte == 0x01:
                        self.data_rx += 1
                    else:
                        self.parity_rx += 1
                    # Check for group change
                    if group_id != self.current_group_id:
                        if self.current_group_id != -1:
                            total_produced += self.flush_group(output_items, produced)
                        self.current_group_id = group_id

                    # Store in buffer
                    # Payload for Parity (Type 5) IS the decoded bytes (XOR sum)
                    # Payload for Data (Type 1) IS the decoded bytes
                    self.group_buffer[slot_id] = decoded
                    self._print_status()

                return required, total_produced
            else:
                self.crc_fail += 1
                self._print_status()
                return 0, 0
        return 0, 0

    def find_sync_soft(self, data_bytes, threshold=2):
        """Finds sync word allowing 'threshold' bit flips."""
        if len(data_bytes) < 4: return -1, 0 # Return tuple
        
        # Convert data to bits
        data_bits = np.unpackbits(np.frombuffer(data_bytes, dtype=np.uint8))
        sync_len = len(self.sync_bits)
        
        # Simple sliding window bit-comparison (could be optimized with correlation)
        # We check every bit position (not just byte-aligned)
        for i in range(len(data_bits) - sync_len):
            diff = np.sum(data_bits[i : i + sync_len] != self.sync_bits)
            if diff <= threshold:
                # Found it! Return (byte_index, bit_shift)
                return i // 8, i % 8
        return -1, 0

    def general_work(self, input_items, output_items):
        if self.finished:
            self.consume(0, len(input_items[0]))
            return -1

        in_buf = input_items[0]
        out_buf = output_items[0]
        produced = 0

        # CRITICAL FIX: Always consume input to prevent hanging
        # If we don't have enough data, consume what we have and wait for more
        if len(in_buf) < 48:
            # Consume all available bytes to prevent deadlock
            self.consume(0, len(in_buf))
            return 0
        
        in_bytes = in_buf.tobytes()
        
        # Find sync with soft-matching
        sync_byte_idx, bit_shift = self.find_sync_soft(in_bytes, threshold=2)
        
        if sync_byte_idx != -1:
            # Shift data based on bit_shift
            shifted_data = self.get_shifted_data(in_bytes[sync_byte_idx : ], bit_shift)
            
            # Now process_packet but sync_idx is 0 because we started shifting FROM the sync word
            consumed, prod = self.process_packet(shifted_data, 0, out_buf, produced)
            
            if consumed > 0:
                # Total bytes to consume from original in_buf: 
                # Re-calculate carefully for 16-byte preamble:
                # sync_byte_idx is the START of the sync word.
                # The preamble of 16 bytes is BEFORE this.
                # So we consume (sync_byte_idx - 16) bytes + preamble + sync + packet
                # Simplest: consume until the end of the packet we just processed.
                total_bits = (sync_byte_idx * 8) + bit_shift + (consumed * 8)
                bytes_to_consume = total_bits // 8
                
                self.consume(0, bytes_to_consume)
                return prod
            else:
                # Sync found but packet failed (e.g. CRC)
                # Move forward 1 byte to avoid getting stuck
                self.consume(0, sync_byte_idx + 1)
                return 0
        
        # No sync found, consume some data to avoid buffer buildup
        # Consume enough to move forward but keep some for sync detection overlap
        bytes_to_consume = max(1, len(in_buf) - 48)
        self.consume(0, bytes_to_consume)
        return 0
