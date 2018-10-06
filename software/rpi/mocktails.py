#!/usr/bin/python

import argparse
import logging
import time
import signal
import sys
import json
import serial
import math, random
import click
import os.path
# TODO: Uncomment this import - it's only available for Pi
# import RPi.GPIO as GPIO 
from six.moves import input
from threading import Thread, Event
import threading
from queue import Queue
from google.rpc import code_pb2

DRINK_SIZE = 12 # size of the cup to fill in ounces
# recipes below assume:
#   bottle 0 = orange juice
#   bottle 1 = sparkling water
#   bottle 2 = grenadine
#   bottle 3 = lemon soda
#   bottle 4 = lime juice
#   bottle 5 = unused
#   bottle 6 = unused
#   bottle 7 = unused
MENU = {
	'SUNSET_COOLER': [
		{ 'bottle' : 0, 'proportion': 4 },
		{ 'bottle' : 1, 'proportion': 8 },
		{ 'bottle' : 2, 'proportion': 1 }
	],
	'CRAZY_DRINK': [
		{ 'bottle' : 0, 'proportion': 6 },
		{ 'bottle' : 1, 'proportion': 6 },
		{ 'bottle' : 2, 'proportion': 6 }
	],
	'ORANGE_BLAST': [
		{ 'bottle' : 0, 'proportion': 4 },
		{ 'bottle' : 1, 'proportion': 1 },
		{ 'bottle' : 3, 'proportion': 1 }
	],
	'CHERRY_BOMB': [
		{ 'bottle' : 3, 'proportion': 8 },
		{ 'bottle' : 2, 'proportion': 1 },
		{ 'bottle' : 4, 'proportion': 1 }
	]
}


# constants
SER_DEVICE = '/dev/ttyACM0' # ensure correct file descriptor for connected arduino
PUMP_SPEED = 0.056356667 # 100 ml / min = 0.056356667 oz / sec
NUM_BOTTLES = 8
PRIME_WHICH = None

def signal_handler(signal, frame):
	""" Ctrl+C handler to cleanup """

	for t in threading.enumerate():
		# print(t.name)
		if t.name != 'MainThread':
			t.shutdown_flag.set()

	print('Goodbye!')
	sys.exit(1)

class SerialThread(Thread):

	def __init__(self, msg_queue):
		Thread.__init__(self)
		self.shutdown_flag = Event()
		self.msg_queue = msg_queue
		# TODO: Uncomment when running on Pi
		# self.serial = serial.Serial(SER_DEVICE, 9600)

	def run(self):

		while not self.shutdown_flag.is_set():

			if not self.msg_queue.empty():
				cmd = self.msg_queue.get()
				# TODO: Uncomment when running on Pi
				# self.serial.write(str.encode(cmd))
				print('Serial sending ' + cmd)

class Mocktails():

	def __init__(self):
	
		logging.basicConfig(level=logging.INFO)

		# handle SIGINT gracefully
		signal.signal(signal.SIGINT, signal_handler)

		# create message queue for communicating between threads
		self.msg_q = Queue()

		# start serial thread
		serial_thread = SerialThread(self.msg_q)
		serial_thread.start()

	def get_pour_time(self, pour_prop, total_prop):
		return (DRINK_SIZE * (pour_prop / total_prop)) / PUMP_SPEED

	def prime_pump_start(self, which_pump):
		PRIME_WHICH = which_pump
		print('Start priming pump ' + PRIME_WHICH)
		self.msg_q.put('b' + PRIME_WHICH + 'r!') # turn on relay

	def prime_pump_end(self):
		if PRIME_WHICH != None:
			print('Stop priming pump ' + PRIME_WHICH)
			self.msg_q.put('b' + PRIME_WHICH + 'l!') # turn off relay
			PRIME_WHICH = None

	def make_drink(self, drink_name):

		print('make_drink()')

		# check that drink exists in menu
		if not drink_name in MENU:
			print('drink "' + drink_name + '" not in menu')
			return

		# get drink recipe
		recipe = MENU[drink_name]
		print(drink_name + ' = ' + str(recipe))

		# sort drink ingredients by proportion
		sorted_recipe = sorted(recipe, key=lambda p: p['proportion'], reverse=True)
		# print(sorted_recipe)

		# calculate time to pour most used ingredient
		total_proportion = 0
		for p in sorted_recipe:
			total_proportion += p['proportion']
		drink_time = self.get_pour_time(sorted_recipe[0]['proportion'], total_proportion)
		print('Drink will take ' + str(math.floor(drink_time)) + 's')

		# for each pour
		for i, pour in enumerate(sorted_recipe):

			# for first ingredient
			if i == 0:

				# start pouring with no delay
				pour_thread = Thread(target=self.trigger_pour, args=([self.msg_q, pour['bottle'], math.floor(drink_time)]))
				pour_thread.start()

			# for other ingredients
			else:

				# calculate the latest time they could start
				pour_time = self.get_pour_time(pour['proportion'], total_proportion)
				latest_time = drink_time - pour_time

				# start each other ingredient at a random time between now and latest time
				delay = random.randint(0, math.floor(latest_time))
				pour_thread = Thread(target=self.trigger_pour, args=([self.msg_q, pour['bottle'], math.floor(pour_time), delay]))
				pour_thread.start()


	def trigger_pour(self, msg_q, bottle_num, pour_time, start_delay=0):

		if bottle_num > NUM_BOTTLES:
			print('Bad bottle number')
			return

		print('Pouring bottle ' + str(bottle_num) + ' for ' + str(pour_time) + 's after a ' + str(start_delay) + 's delay')

		time.sleep(start_delay) # start delay
		msg_q.put('b' + str(bottle_num) + 'r!') # start bottle pour
		time.sleep(pour_time) # wait
		msg_q.put('b' + str(bottle_num) + 'l!') # end bottle pour
