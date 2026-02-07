
import numpy as np
import binascii

class Scrambler:
    """Additive Scrambler using an LFSR P(x) = x^7 + x^4 + 1"""
    def __init__(self, seed=0x7F):
        self.seed = seed
        self.reset()
        
    def reset(self):
        self.state = self.seed
        
    def next_byte(self):
        out = 0
        for i in range(8):
            feedback = ((self.state >> 6) ^ (self.state >> 3)) & 1
            out = (out << 1) | (self.state & 1)
            self.state = ((self.state << 1) & 0x7F) | feedback
        return out

    def process(self, data):
        data_bytes = bytes(data)
        out = bytearray()
        for b in data_bytes:
            out.append(b ^ self.next_byte())
        return bytes(out)

class Hamming74:
    """Standard Hamming (7,4) implementation with single bit error correction"""
    def __init__(self):
        # Encoding table for 4 bits -> 8 bits (using 7 bits actually, 8th is 0)
        # Generator matrix G = [I | P]
        # P = [[1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1]]
        self.enc_table = [0x00, 0x69, 0x2a, 0x43, 0x4e, 0x27, 0x64, 0x0d, 
                          0x71, 0x18, 0x5b, 0x32, 0x3f, 0x56, 0x15, 0x7c]
        
        # Decoding table: maps all 128 possible 7-bit values to the most likely 4-bit nibble
        self.dec_table = {}
        for nibble, codeword in enumerate(self.enc_table):
            self.dec_table[codeword] = nibble
            # Single bit error correction: flip each of the 7 bits
            for bit in range(7):
                self.dec_table[codeword ^ (1 << bit)] = nibble

    def encode(self, nibble):
        return self.enc_table[nibble & 0x0F]

    def decode(self, codeword):
        return self.dec_table.get(codeword & 0x7F, 0)

def get_crc32(data):
    return binascii.crc32(data) & 0xFFFFFFFF

# 10-byte sentinel the source appends after the flush tail.
# The encoder watches for this pattern to trigger END packets.
EOF_SENTINEL = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE, 0xF0, 0x0D])
