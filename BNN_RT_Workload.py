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


current_fi_run = None

BNN_BISTREAM_DIR = '/usr/local/lib/python3.6/dist-packages/bnn/bitstreams/'
PLATFORM = 'pynqZ1-Z2'

xlnk = Xlnk()

server_logger = logging.getLogger('FaultInjServer')
fh = logging.FileHandler('./fault_inj.log')
sh = logging.StreamHandler()

formatter = logging.Formatter('%(asctime)s:%(name)s:[%(levelname)s]: %(message)s')
fh.setFormatter(formatter)
sh.setFormatter(formatter)

server_logger.setLevel(logging.INFO)
server_logger.addHandler(fh)
server_logger.addHandler(sh)


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
        classifier_result_index = classifier.classify_path(image_filename)
        # classifier_result_name = classifier.class_name(classifier_result_index)
        classifier_duration = classifier.usecPerImage
        server_logger.info(f"RESULT: {classifier_result_index} {classifier_duration}")

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

while True:
    choice = input()
    if choice == 'S':
        workload_event.set()
        wl_thread = Thread(target=classify_path, args=("./road_signs/stop.jpg", ))
        wl_thread.start()
    elif choice == 'X':
        workload_event.clear()
        wl_thread.join()
        wl_thread = None
        server_logger.info(f"Workload thread stopped")
    elif choice == 'Q':
        if wl_thread is not None and wl_thread.is_alive():
            workload_event.clear()
            wl_thread.join()
            wl_thread = None
        server_logger.info(f"Quiting")
        break

safe_reboot_event.clear()
wd_thread.join()
