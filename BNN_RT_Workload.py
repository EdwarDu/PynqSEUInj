#!/usr/bin/python3

import bnn
from pynq import Xlnk
from BitstreamMan import BitstreamMan
import os
import sys
import time
from multiprocessing import Process, Pipe, Event
from threading import Thread
import logging
import signal
from PIL import Image
import numpy as np

current_fi_run = None

BNN_BISTREAM_DIR = '/usr/local/lib/python3.6/dist-packages/bnn/bitstreams/'
PLATFORM = 'pynqZ1-Z2'

xlnk = Xlnk()

server_logger = logging.getLogger('FaultInjServer')
fh = logging.FileHandler('/home/xilinx/PynqSEUInj/fault_inj.log')
#sh = logging.StreamHandler()

formatter = logging.Formatter('%(asctime)s:%(name)s:[%(levelname)s]: %(message)s')
fh.setFormatter(formatter)
#sh.setFormatter(formatter)

server_logger.setLevel(logging.INFO)
server_logger.addHandler(fh)
#server_logger.addHandler(sh)


workload_event = Event()


def classify_path(image_filename: str):
    global server_logger

    # server_Logger_in_wl = logging.getLogger('FaultInjServer')
    bnn_networks = {
        'cnvW1A1': ('cifar10', 'road-signs', 'streetview'),
        'cnvW1A2': ('cifar10',),
        'cnvW2A2': ('cifar10',),
        'lfcW1A1': ('mnist', 'chars_merged'),
        'lfcW1A2': ('mnist',)
    }

    network_name = "cnvW1A1"
    classifier_name = "road-signs"

    assert (network_name in bnn_networks.keys())
    assert (classifier_name in bnn_networks[network_name])

    if network_name.startswith('cnv'):
        classifier = bnn.CnvClassifier(network_name, classifier_name, bnn.RUNTIME_HW)
    else:  # 'lfc'
        classifier = bnn.LfcClassifier(network_name, classifier_name, bnn.RUNTIME_HW)

    while workload_event.is_set():
        classifier_details = classifier.classify_image_details(Image.open(image_filename))
        # classifier_result_name = classifier.class_name(classifier_result_index)
        classifier_duration = classifier.usecPerImage
        server_logger.info(f'DETAILS: {",".join([str(x) for x in classifier_details])} RESULT: {np.where(classifier_details == np.max(classifier_details))} {classifier_duration}')
        os.system(f'wall -n "DETAILS: {",".join([str(x) for x in classifier_details])} RESULT: {np.where(classifier_details == np.max(classifier_details))} {classifier_duration}"')
        time.sleep(1)

    xlnk.xlnk_reset()


safe_reboot_event = Event()
safe_reboot_event.set()


def safe_reboot():
    global safe_reboot_event
    # Start hardware watchdog to reboot when the application is stuck
    f_wdt = os.open("/dev/watchdog0", os.O_RDWR)
    while safe_reboot_event.is_set():
        os.write(f_wdt, b'1')  # Keep alive
        time.sleep(3)  # timeout reset is 10s

    os.write(f_wdt, b'V')
    os.close(f_wdt)


wd_thread = Thread(target=safe_reboot)
wd_thread.start()

wl_thread = None


def signal_handler(sig, frame):
    global wl_thread, wd_thread

    if wl_thread is not None and wl_thread.is_alive():
        workload_event.clear()
        wl_thread.join()
        wl_thread = None

    safe_reboot_event.clear()
    wd_thread.join()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)

workload_event.set()
wl_thread = Thread(target=classify_path, args=("/home/xilinx/PynqSEUInj/road_signs/stop.jpg",))
wl_thread.start()

while not os.path.exists("/home/xilinx/PynqSEUInj/kill"):
    time.sleep(1)

os.remove("/home/xilinx/PynqSEUInj/kill")

workload_event.clear()
wl_thread.join()
wl_thread = None

safe_reboot_event.clear()
wd_thread.join()
