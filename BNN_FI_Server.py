#!/usr/bin/python3

import bnn
from pynq import Xlnk
from BitstreamMan import BitstreamMan
import os
import shutil
import sys
import time
from pprint import pprint
from flask import Flask, request, jsonify, abort
from multiprocessing import Process, Pipe, Event
from threading import Thread
import logging


current_fi_run = None

BNN_BISTREAM_DIR = '/usr/local/lib/python3.6/dist-packages/bnn/bitstreams/'
PLATFORM = 'pynqZ1-Z2'

xlnk = Xlnk()

server_logger = logging.getLogger('FaultInjServer')
fh = logging.FileHandler('/home/xilinx/PynqSEUInj/fault_inj.log')
fh.setFormatter(logging.Formatter('%(asctime)s:%(name)s:[%(levelname)s]: %(message)s'))

server_logger.setLevel(logging.INFO)
server_logger.addHandler(fh)


def workload(p: Pipe,
             network_name: str = 'cnvW1A1',
             classifier_name: str = 'road-signs',
             image_filename: str = './images/cross.jpg'):
    """
        for the fault injection, use only road-signs
    """
    # server_Logger_in_wl = logging.getLogger('FaultInjServer')
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
    # classifier_result_name = classifier.class_name(classifier_result_index)
    classifier_duration = classifier.usecPerImage
    p.send({
        'index': classifier_result_index,
        # 'name': classifier_result_name,
        'duration': classifier_duration
    })


FAULTY_BITSTREAM_FOLDER = '/home/xilinx/PynqSEUInj/FAULTY_BITSTREAMS/'
app = Flask(__name__)

fi_p_parent, fi_run_p_child = Pipe()


@app.route('/fault_inj', methods=['POST', ])
def do_fault_injection():
    global current_fi_run
    global fi_run_p_child
    global server_logger

    network_name = request.form.get('network_name')
    faulty_bitstream = request.files.get('faulty_bitstream')

    server_logger.info(f"New run: {faulty_bitstream}")

    target_bs_filename = os.path.join(BNN_BISTREAM_DIR, PLATFORM,
                                      network_name + '-' + PLATFORM + '.bit')

    faulty_bitstream.save(target_bs_filename)
    server_logger.info(f"BS saved")

    current_fi_run = Process(target=workload, args=(fi_run_p_child,
                                                    network_name,
                                                    'road-signs',
                                                    '/home/xilinx/PynqSEUInj/images/cross.jpg'))
    current_fi_run.start()
    server_logger.info(f"Run started")

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
    global current_fi_run, fi_p_parent, fi_run_p_child, xlnk, server_logger

    timeout = request.form.get('timeout')
    timeout = float(timeout) if timeout is not None else 5
    server_logger.info(f'wait_run: timeout {timeout} secs')
    if current_fi_run is None:
        server_logger.warning('wait_run: Not running')
        abort(204)   # NO Content
    else:
        try:
            current_fi_run.join(timeout=timeout)
            if current_fi_run.exitcode is None:
                raise TimeoutError()

            server_logger.info(f'wait_run: Run finished successfully')
            current_fi_run = None
            if fi_p_parent.poll(timeout=timeout):
                class_res = fi_p_parent.recv()
                server_logger.info(f'{class_res}')
            else:
                server_logger.error(f'pipe read timeout for {timeout} secs')
                server_logger.info(f'recreating pipe for next run')
                fi_p_parent, fi_run_p_child = Pipe()
                class_res = {
                    'index': -1,
                    'duration': 0
                }
        except TimeoutError as toe:
            server_logger.warning(f"wait_run: timeout")
            if current_fi_run is not None:
                while current_fi_run.is_alive():
                    server_logger.info(f"terminating run")
                    current_fi_run.terminate()
                    time.sleep(1)
                current_fi_run = None
            server_logger.log('recreating the pipe for next run')
            fi_p_parent, fi_run_p_child = Pipe()
            class_res = {
                'index': -1,
                'duration': 0
            }

        xlnk.xlnk_reset()
        return jsonify(class_res)


@app.route('/reboot', methods=['POST', ])
def reboot():
    global safe_reboot_event, server_logger
    server_logger.warning(f'rebooting ...')
    safe_reboot_event.clear()
    return jsonify({
        'status': 'rebooting'
    })


@app.route('/do_run', methods=['POST', ])
def do_run():
    global current_fi_run
    global fi_run_p_child
    global server_logger

    network_name = request.form.get('network_name')
    server_logger.info(f"New run: NO (NEW) FAULTY BIT")

    current_fi_run = Process(target=workload, args=(fi_run_p_child,
                                                    network_name,
                                                    'road-signs',
                                                    '/home/xilinx/PynqSEUInj/images/cross.jpg'))
    current_fi_run.start()
    server_logger.info(f"Run started")

    return jsonify({
        'running': current_fi_run.is_alive()
    })


safe_reboot_event = Event()
safe_reboot_event.set()


def safe_reboot():
    global safe_reboot_event
    # Start hardware watchdog to reboot when the application is stuck
    f_wdt = os.open("/dev/watchdog0", os.O_RDWR)
    while safe_reboot_event.is_set():
        os.write(f_wdt, b'1')  # Keep alive
        time.sleep(3)  # timeout reset is 10s

    time.sleep(15) # Force to reboot
    # os.write(f_wdt, b'V')
    # os.close(f_wdt)


wd_thread = Thread(target=safe_reboot)
wd_thread.start()

app.run(host='0.0.0.0', port=5200)

wd_thread.join()
