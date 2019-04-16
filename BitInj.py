#!/usr/bin/env python3

from BitstreamMan import BitstreamMan, load_ll_file
import os
from os.path import isfile
import re
from BNN_RoadSign import workload

TARGET_BITSTREAM_FILENAME = "cnvW1A1-pynqZ1-Z2.bit"
ORIGINAL_BITSTREAM = "./PynqBNN_Test/cnvW1A1-pynqZ1-Z2.bit"
ORIGINAL_BITSTREAM_LL = "./PynqBNN_Test/cnvW1A1-pynqZ1-Z2.ll"
FAULTY_BISTREAM = "/usr/local/lib/python3.6/dist-packages/bnn/bitstreams/pynqZ1-Z2/cnvW1A1-pynqZ1-Z2.bit"
WORKLOAD = "python3 ./BNN_RoadSign.py"

print(f"Loading BitStream file: {ORIGINAL_BITSTREAM}")
bman_orig = BitstreamMan(ORIGINAL_BITSTREAM)
print(f"...Done")

print(f"Loading Logic Location File: {ORIGINAL_BITSTREAM_LL}")

assert (isfile(ORIGINAL_BITSTREAM_LL))
ll_lst = []
with open(ORIGINAL_BITSTREAM_LL, 'r') as f_ll:
    for line in f_ll:
        if not line.startswith("Bit "):
            continue
        else:
            line_parts = [x for x in re.split(" |\t|\n", line) if x != '']
            bit_offset = int(line_parts[1])
            frame_addr = int(line_parts[2], 16)
            frame_b_offset = int(line_parts[3])
            bit_dict = {
                "bit_offset": bit_offset,
                "frame_addr": frame_addr,
                "frame_b_offset": frame_b_offset
            }

            for i in range(4, len(line_parts)):
                line_part = line_parts[i]
                key, value = re.split("=", line_part)
                bit_dict[key] = value

            bit_offset = bit_dict['bit_offset']
            bit_value_orig = bman_orig.get_bit(bit_offset)
            # Flip the bit
            print(f"Flipping {bit_dict}")
            bman_orig.set_bit(bit_offset, 1 if bit_value_orig == 0 else 0)
            bman_orig.dump_bitstream(FAULTY_BISTREAM)
            # Launch workload
            workload()
            # Report
            bman_orig.set_bit(bit_offset, bit_value_orig)
