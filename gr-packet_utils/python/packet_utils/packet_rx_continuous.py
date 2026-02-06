
import numpy as np
from gnuradio import gr, digital, blocks
from .packet_decoder_continuous import packet_decoder_continuous

class packet_rx_continuous(gr.hier_block2):
    """
    Continuous Packet Receiver.
    Does not terminate flowgraph.
    """
    def __init__(self, sync_word=0xDEADBEEF, samples_per_symbol=2, sensitivity=1.0):
        gr.hier_block2.__init__(
            self, "Packet RX (Continuous)",
            gr.io_signature(1, 1, np.dtype(np.complex64).itemsize), # Input: Complex
            gr.io_signature(1, 1, np.dtype(np.uint8).itemsize),     # Output: Bytes
        )

        self.demod = digital.gfsk_demod(
            samples_per_symbol=samples_per_symbol,
            sensitivity=sensitivity,
            gain_mu=0.175,
            mu=0.5,
            omega_relative_limit=0.005,
            freq_error=0.0,
            verbose=False,
            log=False
        )
        
        self.packer = blocks.pack_k_bits_bb(8)
        self.decoder = packet_decoder_continuous(sync_word)
        
        self.connect(self, self.demod)
        self.connect(self.demod, self.packer)
        self.connect(self.packer, self.decoder)
        self.connect(self.decoder, self)
