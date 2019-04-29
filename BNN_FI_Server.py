#!/usr/bin/python3

import bnn
from pynq import Xlnk
from BitstreamMan import BitstreamMan
import os
import shutil
import sys
import time
from pprint import pprint
from flask import Flask, request, jsonify
from multiprocessing import Process, Pipe


current_fi_run = None

BNN_BISTREAM_DIR = '/usr/local/lib/python3.6/dist-packages/bnn/bitstreams/'
PLATFORM = 'pynqZ1-Z2'

xlnk = Xlnk()


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


def workload(p: Pipe,
             network_name: str = 'cnvW1A1',
             classifier_name: str = 'road-signs',
             image_filename: str = './images/cross.jpg'):
    """
        for the fault injection, use only road-signs
    """
    bnn_networks = {
        'cnvW1A1': ('cifar10', 'road-signs', 'streetview'),
        'cnvW1A2': ('cifar10', ),
        'cnvW2A2': ('cifar10', ),
        'lfcW1A1': ('mnist', 'chars_merged'),
        'lfcW1A2': ('mnist', )
    }

    assert(network_name in bnn_networks.keys())
    assert(classifier_name in bnn_networks[network_name])

    if network_name.startswith('cnv'):
        classifier = bnn.CnvClassifier(network_name, classifier_name, bnn.RUNTIME_HW)
    else: # 'lfc'
        classifier = bnn.LfcClassifier(network_name, classifier_name, bnn.RUNTIME_HW)

    classifier_result_index = classifier.classify_path(image_filename)
    classifier_result_name = classifier.class_name(classifier_result_index)
    classifier_duration = classifier.usecPerImage
    p.send({
        'index': classifier_result_index,
        'name': classifier_result_name,
        'duration': classifier_duration
    })


FAULTY_BITSTREAM_FOLDER = './FAULTY_BITSTREAMS/'
app = Flask(__name__)

fi_p_parent, fi_run_p_child = Pipe()


@app.route('/fault_inj', methods=['POST', ])
def do_fault_injection():
    global current_fi_run
    global fi_run_p_child

    pprint(request.form)
    pprint(request.files)

    network_name = request.form.get('network_name')
    faulty_bitstream = request.files.get('faulty_bitstream')

    target_bs_filename = os.path.join(BNN_BISTREAM_DIR, PLATFORM,
                                      network_name + '-' + PLATFORM + '.bit')

    faulty_bitstream.save(target_bs_filename)

    current_fi_run = Process(target=workload, args=(fi_run_p_child,
                                                    network_name,
                                                    'road-signs',
                                                    './images/cross.jpg'))
    current_fi_run.start()

    return jsonify({
        'running': current_fi_run.is_alive()
    })


@app.route('/is_running', methods=['GET', 'POST'])
def is_running():
    global current_fi_run
    if current_fi_run is None:
        return jsonify({'running': False})
    elif current_fi_run.is_alive():
        return jsonify({'running': True})
    else:
        return jsonify({'running': False})


@app.route('/wait_run', methods=['POST', 'GET'])
def wait_run():
    global current_fi_run, fi_p_parent, fi_run_p_child, xlnk

    timeout = request.form.get('timeout')
    timeout = float(timeout) if timeout is not None else 5
    print(f'*************[INFO]:Waiting for timeout = {timeout} secs')
    if current_fi_run is None:
        print('*************[ERROR]: Not running')
        return jsonify({
            'index': -1,
            'name': 'fi failed',
            'duration': -1
        })
    else:
        try:
            current_fi_run.join(timeout=timeout)
            if current_fi_run.exitcode is None:
                raise TimeoutError()

            print(f'*************[INFO]: Run finished successfully')
            current_fi_run = None
            if fi_p_parent.poll(timeout=timeout):
                class_res = fi_p_parent.recv()
                print(f'Result ==> {class_res}')
            else:
                print(f'*************[ERROR]: Failed to get results within {timeout} secs')
                print(f'*************[WARNING]: Recreating Pipe')
                fi_p_parent, fi_run_p_child = Pipe()
                class_res = {
                    'index': -1,
                    'name': 'timeout',
                    'duration': 0
                }
        except TimeoutError as toe:
            print('*************[ERROR]: Time out')
            if current_fi_run is not None:
                while current_fi_run.is_alive():
                    print(f'*************[WARNING]: Terminating the run')
                    current_fi_run.terminate()
                    time.sleep(1)
                current_fi_run = None
            print('*************[WARNING]: Recreating the Pipe')
            fi_p_parent, fi_run_p_child = Pipe()
            class_res = {
                'index': -1,
                'name': 'timeout',
                'duration': 0
            }

        xlnk.xlnk_reset()
        return jsonify(class_res)


app.run(host='0.0.0.0', port=5200)

