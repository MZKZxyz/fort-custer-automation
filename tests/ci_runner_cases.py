"""Inert subprocess fixtures for the CI runner's own exit/deadline tests.

The filename intentionally does not match unittest's normal discovery pattern.
"""
import time
import unittest


class Cases(unittest.TestCase):
    def test_pass(self): self.assertTrue(True)
    def test_overwrites_id(self): self.id = 'fixture-request-id'; self.assertTrue(True)
    def test_fail(self): self.fail('intentional runner failure fixture')
    def test_hang(self): time.sleep(30)
