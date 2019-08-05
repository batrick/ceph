"""
Thrasher base class
"""
class Thrasher:

    def __init__(self):
        self.exception = None

    def setexception(self, e):
        """
        Sets the exception.
        Called by the subclasses to store the exception.
        """
        self.exception = e

    def getexception(self):
        """
        returns the exception
        """
        return self.exception
