
import numpy as np
from gnuradio import gr, digital, blocks
from .packet_encoder_continuous import packet_encoder_continuous

class packet_tx_continuous(gr.hier_block2):
    """
    Continuous Packet Transmitter.
    Does not terminate flowgraph.
    """
    def __init__(self, preamble=0xAAAAAAAA, sync_word=0xDEADBEEF, samples_per_symbol=2, sensitivity=1.0, bt=0.35):
        gr.hier_block2.__init__(
            self, "Packet TX (Continuous)",
            gr.io_signature(1, 1, np.dtype(np.uint8).itemsize), # Input: Bytes
            gr.io_signature(1, 1, np.dtype(np.complex64).itemsize), # Output: Complex
        )

        self.encoder = packet_encoder_continuous(preamble, sync_word)
        self.s2v = blocks.stream_to_vector(np.dtype(np.uint8).itemsize, 10)
        self.v2s = blocks.vector_to_stream(np.dtype(np.uint8).itemsize, 48)
        
        self.mod = digital.gfsk_mod(
            samples_per_symbol=samples_per_symbol,
            sensitivity=sensitivity,
            bt=bt,
            verbose=False,
            log=False,
        )
        
        self.connect(self, self.s2v)
        self.connect(self.s2v, self.encoder)
        self.connect(self.encoder, self.v2s)
        self.connect(self.v2s, self.mod)
        self.connect(self.mod, self)
