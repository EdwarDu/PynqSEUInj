#!/usr/bin/env python3

import os
from os.path import isfile
import struct
import sys

"""
WARNING: This is only intended for 7Series Xilinx FPGA
"""


def decode_far_reg(word: int):
    """
    :param word: FAR register value
    :return: tuple for each field
    """
    # 00 0000 0000 0000 0000 0000 0000
    # 11 1                              => 0x0380_0000
    # 00 01                             => 0x0040_0000
    # 00 0011 1110                      => 0x003E_0000
    # 00 0000 0001 1111 1111 10         => 0x0001_FF80
    # 00 0000 0000 0000 0000 0111 1111  => 0x0000_007F
    block_type = (0x0380_0000 & word) >> 23
    top_bottom = (0x0040_0000 & word) >> 22
    row_addr = (0x003E_0000 & word) >> 17
    col_addr = (0x0001_FF80 & word) >> 7
    minor_addr = (0x0000_007F & word)

    if block_type == 0x0:
        block_type_str = "CLB,I/O,CLK"
    elif block_type == 0x1:
        block_type_str = "BRAM"
    elif block_type == 0x2:
        block_type_str = "CFG_CLB"
    else:
        block_type_str = "--"

    if top_bottom == 0x0:
        half = "TOP"
    else:
        half = "BOTTOM"

    return block_type_str, half, row_addr, col_addr, minor_addr

# TODO: COMMAND DICT

def decode_bs_word(word: int):
    """
    decode word in the bistream file
    :param word: word
    :return: meaning
    """
    # 001 xx RRRRRRRRRxxxxx RR xxxxxxxxxxx
    # 111
    # 000 11
    # 000 00 11111111111111 0
    # 000 00 00000000000000 11 00000000000
    # 000 00 00000000000000 00 11111111111
    header_type = (0xE000_0000 & word) >> 29
    op_code = (0x1800_0000 & word) >> 27
    reg_addr = (0x07FF_E000 & word) >> 13
    wc_pt1 = (0x3FF & word)
    wc_pt2 = (0x07FF_FFFF & word)

    reg_addr_dict = {
        0x00: ("CRC", "RW", "CRC Register"),
        0x01: ("FAR", "RW", "Frame Address Register"),
        0x02: ("FDRI", "W", "Frame Data Register, Input Register (write configuration data)"),
        0x03: ("FDRO", "R", "Frame Data Register, Output Register (read configuration data)"),
        0x04: ("CMD", "RW", "Command Register"),
        0x05: ("CTL0", "RW", "Control Register 0"),
        0x06: ("MASK", "RW", "Masking Register for CTL0 and CTL1"),
        0x07: ("STAT", "R", "Status Register"),
        0x08: ("LOUT", "W", "Legacy Output Register for daisy chain"),
        0x09: ("COR0", "RW", "Configuration Option Register 0"),
        0x0A: ("MFWR", "W", "Multiple Frame Write Register"),
        0x0B: ("CBC", "W", "Initial CBC Value Register"),
        0x0C: ("IDCODE", "RW", "Device ID Register"),
        0x0D: ("AXSS", "RW", "User Access Register"),
        0x0E: ("COR1", "RW", "Configuration Option Register 1"),
        0x10: ("WBSTAR", "RW", "Warm Boot Start Address Register"),
        0x11: ("TIMER", "RW", "Watchdog Timer Register"),
        0x16: ("BOOTSTS", "R", "Boot History Status Register "),
        0x18: ("CTL1", "RW", "Control Register 1"),
        0x1F: ("BSPI", "RW", "BPI/SPI Configuration Options Register")
    }

    if header_type == 0x1:
        header_type_str = "PT1"
        if op_code == 0x0:
            op_code_str = "NOP"
        elif op_code == 0x1:
            op_code_str = "R"
        elif op_code == 0x2:
            op_code_str = "W"
        else:
            op_code_str = "--"

        if reg_addr in reg_addr_dict.keys():
            reg = reg_addr_dict[reg_addr]
        else:
            reg = None

        wc = wc_pt1

        return header_type_str, op_code_str, reg, wc
    elif header_type == 0x2:
        header_type_str = "PT2"
        wc = wc_pt2

        return header_type_str, wc
    else:
        header_type_str = "--"
        return header_type_str,


def read_int16_from_file(f):
    d = f.read(2)
    assert(d != '')
    return struct.unpack('>H', d)[0]


def read_int32_from_file(f):
    d = f.read(4)
    assert(d != '')
    return struct.unpack('>I', d)[0]


class BitstreamMan:
    """
    Class for manipulating bitstream for
        Pynq
    """

    def __init__(self, bitstream_file: str):
        if isfile(bitstream_file):
            self.bs_file = bitstream_file
        else:
            raise ValueError(f"{bitstream_file} is not a valid file")

        self.bs_words = []
        self.bs_bin = None

        with open(self.bs_file, "rb") as f_bs:
            # https://blog.aeste.my/2013/09/30/detailed-look-at-bitstreams-and-a-taste-of-base64-and-sd-card-crc/
            # strip the bitstream file header
            field_len = read_int16_from_file(f_bs)
            field_data = f_bs.read(field_len)  # data words
            print(field_data)
            field_len = read_int16_from_file(f_bs)
            assert(field_len == 1)

            while True:
                field_token = f_bs.read(1)  # Token
                if field_token == b'':  # END OF FILE
                    break

                field_token_value = field_token[0]

                if field_token_value == 0x61:
                    # Design name
                    field_len = read_int16_from_file(f_bs)
                    field_data = f_bs.read(field_len)
                    self.design_name = field_data.decode('utf-8')
                elif field_token_value == 0x62:
                    # Part Name
                    field_len = read_int16_from_file(f_bs)
                    field_data = f_bs.read(field_len)
                    self.part_name = field_data.decode('utf-8')
                elif field_token_value == 0x63:
                    # Date
                    field_len = read_int16_from_file(f_bs)
                    field_data = f_bs.read(field_len)
                    self.design_date = field_data.decode('utf-8')
                elif field_token_value == 0x64:
                    # Time
                    field_len = read_int16_from_file(f_bs)
                    field_data = f_bs.read(field_len)
                    self.design_time = field_data.decode('utf-8')
                elif field_token_value == 0x65:
                    # bitstream bin
                    field_len = read_int32_from_file(f_bs)
                    field_data = f_bs.read(field_len)
                    self.bs_bin = field_data
                else:
                    raise ValueError(f"{field_token} UNKNOWN")

        assert(self.bs_bin is not None)

        for i in range(0, len(self.bs_bin), 4):
            self.bs_words.append(struct.unpack('>I', self.bs_bin[i:i+4])[0])

    def decode_bitstream(self, fout=sys.stdout):
        word_index = 0
        while word_index < len(self.bs_words):
            word = self.bs_words[word_index]
            decode_res = decode_bs_word(word)
            if decode_res[0] == '--':
                print(f"{hex(word)[2:].zfill(8)} => DUMMY", file=fout)
                word_index += 1
            elif decode_res[0] == "PT1":
                op_code_str = decode_res[1]
                reg_name, reg_perm, reg_descr = decode_res[2]
                wc = decode_res[3]
                if op_code_str == "NOP":
                    print(f"{hex(word)[2:].zfill(8)} => NOP", file=fout)
                    assert(wc == 0x0)
                elif op_code_str == "R" or op_code_str == "W":
                    print(f"{hex(word)[2:].zfill(8)} => {op_code_str} {reg_name} {reg_perm}", file=fout)
                    #for word_index_i in range(1, wc+1):
                    #    print(f"\t{hex(self.bs_words[word_index+word_index_i])[2:].zfill(8)}", file=fout)
                else:
                    raise ValueError(f"{hex(word)[2:].zfill(8)} => {op_code_str} : UNKNOWN")

                word_index += wc + 1
            elif decode_res[0] == "PT2":
                wc = decode_res[1]
                #for word_index_i in range(1, wc + 1):
                #    print(f"\t{hex(self.bs_words[word_index + word_index_i])[2:].zfill(8)}", file=fout)
                word_index += wc
            else:
                raise ValueError(f"{decode_res} UNKNOWN")


if __name__ == '__main__':
    bman = BitstreamMan("./PynqBNN_Test/cnvW1A1-pynqZ1-Z2.bit")
    bman.decode_bitstream()
