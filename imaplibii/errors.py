


class Error(Exception):
    """Logical errors - debug required"""
class Abort(Exception):
    """Service errors - close and retry"""
class ReadOnly(Exception):
    """Mailbox status changed to READ-ONLY"""

class NotAvailable(Exception): pass
