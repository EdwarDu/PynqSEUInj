#!/usr/bin/env python3

import sys
import os
import time
from threading import Thread, Lock, Event
import requests
from BitstreamMan import BitstreamMan, load_ll_file
import sqlite3
import shutil
import random


server_lst = ['http://pynq1:5200',
              'http://pynq2:5200',
              'http://pynq3:5200',
              'http://pynq4:5200',
              'http://pynq5:5200']

NETWORK_NAME = 'cnvW1A1'
PLATFORM = 'pynqZ1-Z2'

fault_list = []
fault_list_lock = Lock()

db_conn = sqlite3.connect('faults_inj_res_semu.db', check_same_thread=False)
db_conn.execute('''CREATE TABLE IF NOT EXISTS semu_faults (
bits TEXT PRIMARY KEY, 
executed VARCHAR(1), 
frame_addr INT, 
frame_b_offset INT,
props TEXT,
class_index INT,
class_name TEXT,
class_duration INT)''')
db_conn.commit()
db_conn_lock = Lock()


def is_fault_executed(conn, conn_lock, bits):
    with conn_lock:
        c = conn.cursor()
        c.execute('SELECT * FROM semu_faults where bits=? and executed=?', (bits, 'Y'))
        r = c.fetchone()
        conn.commit()
        if r is None:
            return False
        else:
            return True


def update_fault_rec(conn, conn_lock,
                     bits,
                     executed='Y',
                     frame_addr=None,
                     frame_b_offset=None,
                     bit_props=None,
                     class_index=None,
                     class_name=None,
                     class_duration=None):
    with conn_lock:
        c = conn.cursor()
        c.execute('insert or ignore into semu_faults (bits, executed) values (?, ?)', (bits, "N"))
        conn.commit()
        sql_update_command = 'update semu_faults set '
        temp_lst = []
        params_lst = []
        if executed is not None:
            temp_lst.append('executed=?')
            params_lst.append(executed)
        if frame_addr is not None:
            temp_lst.append('frame_addr=?')
            params_lst.append(frame_addr)
        if frame_b_offset is not None:
            temp_lst.append('frame_b_offset=?')
            params_lst.append(frame_b_offset)
        if bit_props is not None:
            temp_lst.append('props=?')
            params_lst.append(bit_props)
        if class_index is not None:
            temp_lst.append('class_index=?')
            params_lst.append(class_index)
        if class_name is not None:
            temp_lst.append('class_name=?')
            params_lst.append(class_name)
        if class_duration is not None:
            temp_lst.append('class_duration=?')
            params_lst.append(class_duration)

        sql_update_command += ','.join(temp_lst)
        sql_update_command += ' where bits=?'
        params_lst.append(bits)

        c.execute(sql_update_command, params_lst)
        conn.commit()


def client_thread(kill_switch: Event, flist_lock: Lock, server: str, conn, conn_lock):
    global fault_list

    while kill_switch.is_set():
        with flist_lock:
            if len(fault_list) != 0:
                fault = fault_list.pop(0)
            else:
                fault = None

        if fault is None:
            time.sleep(1)
        else:
            faulty_bitstream = fault['faulty_bitstream']
            network_name = fault['network_name']
            faulty_bits = fault['bits']

            print(f'{server}: Launching fault injection with bitstream {faulty_bitstream} x {faulty_bits} ')

            try:
                r = requests.post(server + '/fault_inj',
                                  files={
                                    'faulty_bitstream': open(faulty_bitstream, 'rb')
                                  },
                                  data={
                                      'network_name': network_name,
                                  })

                if r.status_code != 200:
                    print(f'{server}: Failed to launch fault injection on server {server}')
                    time.sleep(10)
                    continue

                r = requests.post(server + '/wait_run',
                                  data={
                                      'timeout': 10
                                  })

                if r.status_code != 200:
                    print(f'{server}: Failed to retrieve fault injection results')
                    time.sleep(10)
                    continue
            except Exception:
                time.sleep(10)
                continue

            fi_result = r.json()
            class_index = fi_result['index']
            class_name = fi_result['name']
            class_duration = fi_result['duration']

            print(f'{server}: FI = {class_index}, {class_name}, {class_duration}')

            update_fault_rec(conn, conn_lock, bits=faulty_bits,
                             executed='Y',
                             class_index=class_index,
                             class_name=class_name,
                             class_duration=class_duration)

            # Clean up
            os.remove(faulty_bitstream)


def random_select_m_in_n(m: int, n: list):
    assert(m <= len(n))

    if m == 0:
        return []
    elif m == len(n):
        return n
    else:
        i = random.randint(0, len(n)-1)
        selected = [n[i], ]
        rest = [n[j] for j in range(0, len(n)) if j != i]

        return selected + random_select_m_in_n(m-1, rest)


def genrate_faults(flist_lock: Lock,
                   original_bs_file: str,
                   original_ll_file: str):
    global fault_list, NETWORK_NAME, PLATFORM
    global db_conn, db_conn_lock

    bman = BitstreamMan(original_bs_file)

    # Load LL file
    # print(f"Loading Logic Location file {original_ll_file} ...")
    # ll_list = load_ll_file(original_ll_file)
    # print(f"Done ... total faults {total_faults}")

    index = 1
    total_faults = 10000
    while index < total_faults:
        frame_index = random.randint(0, bman.n_frames-1)
        frame_b_offset = random.randint(0, bman.N_WORDS_IN_FRAME * 32 - 3)

        n_bits = 4

        bits_offset = []
        for frame_i in (frame_index, frame_index+1):
            for frame_b_i in range(frame_b_offset, frame_b_offset+3):
                bits_offset.append(frame_i * bman.N_WORDS_IN_FRAME*32 + frame_b_i)

        actual_bits_offset = sorted(random_select_m_in_n(n_bits, bits_offset))
        bits_str = '-'.join([str(x) for x in actual_bits_offset])

        if is_fault_executed(db_conn, db_conn_lock, bits_str):
            continue

        print(f'scheduling {index} out of {total_faults} with {bits_str}')

        bit_props = 'RANDOM SEMU_'+str(n_bits)
        update_fault_rec(db_conn, db_conn_lock, bits=bits_str,
                         executed='N',
                         frame_addr=hex(frame_index),
                         frame_b_offset=frame_b_offset,
                         bit_props=bit_props)

        for bit_offset in actual_bits_offset:
            bit_value = bman.get_bit(bit_offset)
            bit_value_f = 0 if bit_value == 1 else 1
            bman.set_bit(bit_offset, bit_value_f)

        faulty_bitstream_file = f'./FAULTY_BITSTREAMS/{NETWORK_NAME}-{PLATFORM}-F{bits_str}.bit'
        bman.dump_bitstream(faulty_bitstream_file)

        for bit_offset in actual_bits_offset:
            bit_value = bman.get_bit(bit_offset)
            bit_value_f = 0 if bit_value == 1 else 1
            bman.set_bit(bit_offset, bit_value_f)

        while True:
            with flist_lock:
                if len(fault_list) >= 50:
                    pass
                else:
                    fault_list.append({
                        'faulty_bitstream': faulty_bitstream_file,
                        'network_name': NETWORK_NAME,
                        'bits': bits_str
                    })
                    index += 1
                    break

            time.sleep(1)

    while True:
        with flist_lock:
            if len(fault_list) != 0:
                pass
            else:
                break

        time.sleep(1)


thread_kill_switchs = []
threads = []

for s in server_lst:
    kill_s = Event()
    kill_s.set()
    t = Thread(target=client_thread, args=(kill_s, fault_list_lock, s, db_conn, db_conn_lock))
    t.start()
    thread_kill_switchs.append(kill_s)
    threads.append(t)

genrate_faults(fault_list_lock, original_bs_file=f"./bitstreams/{NETWORK_NAME}-{PLATFORM}.bit",
               original_ll_file=f"./bitstreams/{NETWORK_NAME}-{PLATFORM}.ll")


for kill_s in thread_kill_switchs:
    kill_s.clear()

for t in threads:
    t.join()

db_conn.close()
