

from weakref import ref
from overwatch import tagged, untagged, continuation

dispatch_map = {
    tagged: 'tagged',
    untagged: 'untagged',
    continuation: 'continuation'
}

class response_handler(object):
    def __init__(self, imapll):
        self._imapll = ref(imapll)

    def __call__(self, response):
        try:
            m = '%s_%s' % (dispatch_map[type(response)], response.rtype)
        except AttributeError:
            m = dispatch_map[type(response)]
        return getattr(self, m)(response)

    def tagged_ok(self, response):
        with self._imapll()._state_lock:
            del self._imapll().state

    def untagged_fetch(self, response):
        cmd = self._imapll()._tagref[self._imapll().state]
        cmd.responses.append(response)

