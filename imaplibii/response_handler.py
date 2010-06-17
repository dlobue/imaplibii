

from weakref import proxy

from imapcommands import AUTH, NONAUTH, SELECTED, LOGOUT
from errors import Error, Abort

class response_handler(object):
    def __init__(self, imapll):
        self._imapll = proxy(imapll)

    def __call__(self, response):
        try:
            m = '%s_%s' % (response.__class__.__name__, response.rtype)
        except AttributeError:
            m = response.__class__.__name__
        return getattr(self, m)(response)


    def continuation(self, response):
        cmd = self._imapll._tagref[self._imapll.state]
        c = cmd.send(response.data)
        self._imapll.transport.write(c)


    # Status responses

    def untagged_ok(self, response):
        """
        indicates an information-only message; the nature of the information
        MAY be indicated by a response code.

        Also used as one of three possible greetings at connection startup. 
        It indicates that the connection is not yet authenticated and that a
        LOGIN command is needed.
        """
        with self._imapll._state_lock:
            if self._imapll.state is LOGOUT:
                self._imapll.state = NONAUTH
                self._imapll.welcome = response


    def untagged_no(self, response):
        """
        This is a warning from the server. Command will still complete
        successfully.
        """
        pass

    def untagged_bad(self, response):
        """
        Indicates a protocol-level error for which the associated command can
        not be determined; it can also indicate an internal server failure.
        """
        pass

    def untagged_bye(self, response):
        #FIXME need to continue reading until EOF
        self._imapll.transport.close()
        self._imapll.state = LOGOUT

    def untagged_preauth(self, response):
        with self._imapll._state_lock:
            if self._imapll.state is LOGOUT:
                self._imapll.state = AUTH
                self._imapll.welcome = response

    def tagged_ok(self, response):
        with self._imapll._state_lock:
            assert self._imapll.state == response.tag
            del self._imapll.state

    def tagged_no(self, response):
        with self._imapll._state_lock:
            assert self._imapll.state == response.tag
            del self._imapll.state

        e = 'Encountered error running command. IMAP Server says: %s' % response.data
        raise Error(e)

    def tagged_bad(self, response):
        with self._imapll._state_lock:
            assert self._imapll.state == response.tag
            del self._imapll.state

        e = 'Bad command. IMAP Server says: %s' % response.data
        raise Error(e)




    # Server and Mailbox Status Responses

    def untagged_capability(self, response):
        pass

    def untagged_list(self, response):
        pass

    def untagged_lsub(self, response):
        pass

    def untagged_status(self, response):
        pass

    def untagged_search(self, response):
        pass

    def untagged_flags(self, response):
        pass



    # Mailbox Size Responses

    def untagged_exists(self, response):
        pass

    def untagged_recent(self, response):
        pass



    # Message Status Responses

    def untagged_expunge(self, response):
        pass

    def untagged_fetch(self, response):
        cmd = self._imapll._tagref[self._imapll.state]
        cmd.responses.append(response)


