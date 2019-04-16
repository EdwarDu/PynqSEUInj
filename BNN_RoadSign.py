#!/usr/bin/python3

import bnn
from BitstreamMan import BitstreamMan
import os
import shutil
import sys
import time

classifier_result_index = None
classifier_result_name = None
classifier_duration = None


def generate_faulty(original_bitstream_filename: str,
                    bit_offset: int,
                    faulty_bitstream_filename: str = None):
    if faulty_bitstream_filename is None:
        faulty_bitstream_filename = original_bitstream_filename + 'F' + str(bit_offset)

    start_time = time.time()
    orig_bs = BitstreamMan(original_bitstream_filename)
    end_time = time.time()
    print(f"Loading {original_bitstream_filename} cost {end_time-start_time} seconds")

    bit_value = orig_bs.get_bit(bit_offset)
    bit_value = 0 if bit_value == 1 else 1
    orig_bs.set_bit(bit_offset, bit_value)
    start_time = time.time()
    orig_bs.dump_bitstream(faulty_bitstream_filename)
    end_time = time.time()
    print(f"Dumping {faulty_bitstream_filename} cost {end_time - start_time} seconds")


def workload(network_name: str = 'cnvW1A1',
             faulty_bit_offset : int = None,
             classifier_name: str = 'road-signs',
             image_filename: str = './images/cross.jpg'):
    """
        for the fault injection, use only road-signs
    """
    global classifier_result_index
    global classifier_result_name
    global classifier_duration

    BNN_BISTREAM_DIR='/usr/local/lib/python3.6/dist-packages/bnn/bitstreams/'
    PLATFORM='pynqZ1-Z2'

    bnn_networks = {
        'cnvW1A1': ('cifar10', 'road-signs', 'streetview'),
        'cnvW1A2': ('cifar10', ),
        'cnvW2A2': ('cifar10', ),
        'lfcW1A1': ('mnist', 'chars_merged'),
        'lfcW1A2': ('mnist')
    }

    assert(network_name in bnn_networks.keys())
    assert(classifier_name in bnn_networks[network_name])

    orig_bs_filename = os.path.join(BNN_BISTREAM_DIR, PLATFORM,
                                    network_name + '-' + PLATFORM + '.bit.orig')
    target_bs_filename = os.path.join(BNN_BISTREAM_DIR, PLATFORM,
                                      network_name + '-' + PLATFORM + '.bit')

    if faulty_bit_offset is not None:
        start_time = time.time()
        generate_faulty(original_bitstream_filename=orig_bs_filename,
                        bit_offset=faulty_bit_offset,
                        faulty_bitstream_filename=target_bs_filename)
        end_time = time.time()
        print(f'Generating faulty bit cost {end_time-start_time} seconds')
    else:
        shutil.copy2(src=orig_bs_filename, dst=target_bs_filename)

    if network_name.startswith('cnv'):
        classifier = bnn.CnvClassifier(network_name, classifier_name, bnn.RUNTIME_HW)
    else: # 'lfc'
        classifier = bnn.LfcClassifier(network_name, classifier_name, bnn.RUNTIME_HW)

    classifier_result_index = classifier.classify_path(image_filename)
    classifier_result_name = classifier.class_name(classifier_result_index)
    classifier_duration = classifier.usecPerImage


workload(network_name='cnvW1A1',
         faulty_bit_offset=int(sys.argv[1]),
         classifier_name='road-signs',
         image_filename='./images/stop.jpg')

print(classifier_result_index, classifier_result_name, classifier_duration)
