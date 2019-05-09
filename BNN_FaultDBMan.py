#!/usr/bin/env python3

import sqlite3
from threading import Lock
import logging
from BitstreamMan import BitstreamMan
from BitstreamMan import load_ll_file
import requests
import os
import time
import random


class BNN_FaultDBMan:
    """
    Helper (Man) class for managing (sqlite3) database for recording fault injection results
    """

    def __init__(self, db_filename):
        self.db_conn = sqlite3.connect(db_filename, check_same_thread=False)
        self.db_cursor = self.db_conn.cursor()
        self.db_cursor.execute('''CREATE TABLE IF NOT EXISTS faults (
            bits TEXT PRIMARY KEY, 
            status VARCHAR(1), 
            frame_addr INT, 
            frame_b_offset INT,
            props TEXT,
            class_index INT,
            class_duration INT)''')
        self.db_conn.commit()
        self.db_conn_lock = Lock()

    def is_fault_executed(self, bits: str):
        with self.db_conn_lock:
            self.db_cursor.execute('SELECT * FROM faults where bits=? and status=?', (bits, 'E'))
            r = self.db_cursor.fetchone()
            self.db_conn.commit()
            if r is None:
                return False
            else:
                return True

    def update_fault(self, bits, status=None, frame_addr=None, frame_b_offset=None,
                     props=None, class_index=None, class_duration=None):
        with self.db_conn_lock:
            self.db_cursor.execute('insert or ignore into faults (bits) values (?)', (bits,))
            self.db_conn.commit()
            sql_update_command = 'update faults set '
            temp_lst = []
            params_lst = []
            if status is not None:
                temp_lst.append('status=?')
                params_lst.append(status)
            if frame_addr is not None:
                temp_lst.append('frame_addr=?')
                params_lst.append(frame_addr)
            if frame_b_offset is not None:
                temp_lst.append('frame_b_offset=?')
                params_lst.append(frame_b_offset)
            if props is not None:
                temp_lst.append('props=?')
                params_lst.append(props)
            if class_index is not None:
                temp_lst.append('class_index=?')
                params_lst.append(class_index)
            if class_duration is not None:
                temp_lst.append('class_duration=?')
                params_lst.append(class_duration)

            sql_update_command += ','.join(temp_lst)
            sql_update_command += ' where bits=?'
            params_lst.append(bits)

            self.db_cursor.execute(sql_update_command, params_lst)
            self.db_conn.commit()

    def get_fault(self, bits):
        with self.db_conn_lock:
            self.db_cursor.execute('select * from faults where bits=?', (bits,))
            r = self.db_cursor.fetchall()
            return r

    def get_all_faults(self):
        with self.db_conn_lock:
            self.db_cursor.execute('select * from faults')
            r = self.db_cursor.fetchall()
            return r


class BNN_FaultInjMan:
    NETWORK_NAME = 'cnvA1W1'
    PLATFORM_NAME = 'pynqZ1-Z2'
    """
    Helper (man) class for managing
    fault generation, faulty bitstream generation,
    and fault injection launch in the server (Pynq) board
    """
    def __init__(self, golden_bitstream, logic_location_filename):
        self.db_man = BNN_FaultDBMan('bnn_faults.db')
        self.fault_list = []
        self.server_list = []
        self.server_list_lock = Lock()
        self.golden_bs = golden_bitstream

        # set up the logger
        self.logger = logging.getLogger('FaultInjMan')

        formatter = logging.Formatter('%(asctime)s:%(name)s:[%(levelname)s]: %(message)s')
        fh = logging.FileHandler('fault_inj.log')
        fh.setFormatter(formatter)
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)

        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(fh)
        self.logger.addHandler(sh)

        self.logger.info(f'Loading Bitstream {self.golden_bs}')
        self.bman = BitstreamMan(self.golden_bs)
        self.logger.info(f'Done')

        self.logger.info(f'Loading Logic Location file {logic_location_filename}')
        self.ll_lst = load_ll_file(logic_location_filename)
        self.logger.info(f'{len(self.ll_lst)} bits loaded')

    def add_server(self, server_url):
        with self.server_list_lock:
            self.server_list.append({
                'url' : server_url,
                'status': 'idle',
                'last_ts': 0
            })

    def pick_server(self):
        with self.server_list_lock:
            idle_servers = [x for x in self.server_list if x['status'] == 'idle']
            if len(idle_servers) == 0:
                return None
            else:
                pick_server = sorted(idle_servers, key = lambda x : x['last_ts'])[0]
                pick_server['status'] = 'busy'
                pick_server['last_ts'] = time.time()
                return pick_server['url']

    def set_server_status(self, server_url, status):
        with self.server_list_lock:
            s = [x for x in self.server_list if x['url'] == server_url]
            if len(s) == 0:
                # no such server
                return False
            else:
                s = s[0]
                s['status'] = status
                return True

    def refresh_dead_servers(self):
        with self.server_list_lock:
            dead_servers = [x for x in self.server_list if x['status']=='dead']
            for s in dead_servers:
                try:
                    r = requests.get(s['url'] + '/is_running')
                    if r.status_code == 200:
                        s['status'] = 'idle' if not r.json()['running'] else 'busy'
                except Exception as exp:
                    pass # remain dead

    def any_dead_server(self):
        with self.server_list_lock:
            dead_servers = [x for x in self.server_list if x['status'] == 'dead']
            return True if len(dead_servers) != 0 else False

    def generate_faulty_bs(self, bits, faulty_bs_filename):
        """Not thread-safe, should be called when generating fault"""
        # Flip the bits
        for bit in bits:
            bit_value = self.bman.get_bit(bit)
            bit_value_f = 0 if bit_value == 1 else 1
            self.bman.set_bit(bit, bit_value_f)

        self.bman.dump_bitstream(faulty_bs_filename)
        # Flip the bits back
        for bit in bits:
            bit_value = self.bman.get_bit(bit)
            bit_value_f = 0 if bit_value == 1 else 1
            self.bman.set_bit(bit, bit_value_f)

    def launch_fault_in_server(self, fault, server_url):
        faulty_bits = fault['bits']
        network_name = BNN_FaultInjMan.NETWORK_NAME
        faulty_bits_str = '-'.join([str(x) for x in faulty_bits])
        faulty_bitstream_fname = fault['faulty_bitstream']

        # Generating faulty bitstream
        # faulty_bitstream_fname = './FAULTY_BITSTREAM/' + \
        #                   BNN_FaultInjMan.NETWORK_NAME + \
        #                   BNN_FaultInjMan.PLATFORM_NAME + \
        #                   faulty_bits_str + '.bit'
        # self.generate_faulty_bs(faulty_bits, faulty_bitstream_fname)

        self.logger.info(f'Launching {fault} to {server_url}')

        try:
            r = requests.post(server_url + '/fault_inj',
                              files={
                                  'faulty_bitstream': open(faulty_bitstream_fname, 'rb')
                              },
                              data={
                                  'network_name': network_name,
                              })

            if r.status_code != 200:
                self.set_server_status(server_url, 'dead')
                self.logger.error(f'{server_url} failed to execute')
                return False

            r = requests.post(server_url + '/wait_run',
                              data={
                                  'timeout': 10
                              })

            if r.status_code != 200:
                self.set_server_status(server_url, 'dead')
                self.logger.error(f'{server_url} failed to respond to wait_run')
                return False
        except Exception as exp:
            self.set_server_status(server_url, 'dead')
            self.logger.error(f'{server_url} failed with {exp}')
            return False

        # Successful run
        fi_result = r.json()
        class_index = fi_result['index']
        class_duration = fi_result['duration']

        self.logger.info(f'Fault {fault} injection on {server_url} returns {fi_result}')

        self.db_man.update_fault(bits=faulty_bits_str,
                                 status='E',
                                 class_index=class_index,
                                 class_duration=class_duration)

        # Clean up
        os.remove(faulty_bitstream_fname)
        self.set_server_status(server_url, 'idle')
        return True

    def generate_fault_inj_camp_seu_random(self, n_faults):
        bit = random.randint(0, self.bman.N_WORDS_IN_FRAME * self.bman.n_frames * 32)
        faulty_bits_str = str(bit)
        faulty_bs_fname = './FAULTY_BITSTREAM/' + \
                          BNN_FaultInjMan.NETWORK_NAME + \
                          BNN_FaultInjMan.PLATFORM_NAME + \
                          faulty_bits_str + '.bit'
        fault = {
            'bits': [bit, ],
            'faulty_bitstream': faulty_bs_fname
        }

        if not self.db_man.is_fault_executed(faulty_bits_str):
            pass

    def fault_work_thread(self, bits):
        faulty_bits_str = '-'.join([str(x) for x in bits])
        faulty_bs_fname = './FAULTY_BITSTREAM/' + \
                          BNN_FaultInjMan.NETWORK_NAME + \
                          BNN_FaultInjMan.PLATFORM_NAME + \
                          faulty_bits_str + '.bit'
        self.generate_faulty_bs(bits, faulty_bs_fname)
        fault = {
            'bits': bits,
            'faulty_bitstream': faulty_bs_fname
        }
        while True:
            server_url = self.pick_server()
            if server_url is None:
                # no free server now
                time.sleep(5)
                continue
            else:
                self.launch_fault_in_server(fault, server_url)
                break





