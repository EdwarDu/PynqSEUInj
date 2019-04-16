#!/usr/bin/python3

import bnn
from PIL import Image
from pynq import Xlnk, Overlay, PL
import time
from BitstreamMan import BitstreamMan
import os

classifier_result_index = None
classifier_result_name = None
classifier_duration = None


def generate_faulty(original_bitstream_filename: str,
					bit_offset: int,
					faulty_bitstream_filename: str = None):
	if faulty_bitstream_filename is None:
		faulty_bitstream_filename = original_bitstream_filename + 'F' + str(bit_offset)
	
	orig_bs = BitstreamMan(original_bitstream_filename)
	bit_value = orig_bs.get_bit(bit_offset)
	bit_value = 0 if bit_value == 1 else 1
	orig_bs.set_bit(bit_offset, bit_value)
	orig_bs.dump_bitstream(faulty_bitstream_filename)


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

	bnn_networks = {
		'cnvW1A1' : ('cifar10', 'road-signs', 'streetview'),
		'cnvW1A2' : ('cifar10', ),
		'cnvW2A2' : ('cifar10', ),
		'lfcW1A1' : ('mnist', 'chars_merged'),
		'lfcW1A2' : ('mnist') 
	}

	assert(network_name in bnn_networks.keys())
	assert(classifier_name in bnn_networks[network_name])

	if network_name.startswith('cnv'):
		classifier = bnn.CnvClassifier(network_name, classifier_name, bnn.RUNTIME_HW)
	else: # 'lfc'
		classifier = bnn.LfcClassifier(network_name, classifier_name, bnn.RUNTIME_HW)

	if faulty_bit_offset is not None:
		original_bs_file = classifier.bnn.bitstream_path
		original_bs_file_pre, ext = os.path.splitext(original_bs_file)
		faulty_bs_file = './bitstreams/' + network_name + '-F' + str(faulty_bit_offset) + '.bit'
		os.symlink(dst='./bitstreams/' + network_name + '-F' + str(faulty_bit_offset) + '.tcl',
					src=original_bs_file_pre + '.tcl')
		generate_faulty(original_bitstream_filename=original_bs_file, 
						bit_offset=faulty_bit_offset,
						faulty_bitstream_filename=faulty_bs_file)
		# Force to load the faulty bitstream
		Overlay(faulty_bs_file).download()

	img = Image.open(image_filename)

	classifier_result_index = classifier.classify_image(img)
	classifier_result_name = classifier.class_name(classifier_result_index)
	classifier_duration = classifier.usecPerImage

workload(network_name='cnvW1A1', 
		 faulty_bit_offset=None, 
		 classifier_name='road-signs', 
		 image_filename='./images/cross.jpg')

print(classifier_result_index, classifier_result_name, classifier_duration)
