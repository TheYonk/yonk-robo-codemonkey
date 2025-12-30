"""Example module for testing indexing."""
import os
import sys


def hello_world():
    """Say hello to the world."""
    return "Hello, World!"


def add_numbers(a, b):
    """Add two numbers."""
    return a + b


class Calculator:
    """A simple calculator class."""

    def __init__(self):
        """Initialize the calculator."""
        self.result = 0

    def add(self, x):
        """Add to the result."""
        self.result += x
        return self.result

    def subtract(self, x):
        """Subtract from the result."""
        self.result -= x
        return self.result
