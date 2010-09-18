

from weakref import proxy

from utils import command, null_handler
from imapcommands import AUTH, NONAUTH, SELECTED, LOGOUT
from errors import Error, Abort

class response_handler(object):
    def __init__(self, imapll):
        self._imapll = proxy(imapll)

    def __call__(self, response):
        try:
            m = '%s_%s' % (response.__class__.__name__, response.type)
        except AttributeError:
            m = response.__class__.__name__
        try:
            cmd = self._imapll.state.cmd
            return getattr(self, '%s_%s' % (cmd, m))(response)
        except AttributeError:
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
        if type(self._imapll.state) is command:
            pass
        else:
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
        ccb = self._imapll._tagref[response.tag].completion_cb
        if ccb is not None:
            ccb(response)
        with self._imapll._state_lock:
            assert self._imapll.state == response.tag
            del self._imapll.state
        #XXX: check command queue for next command and send it
        #XXX: if command queue is empty, kill loop?

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


    # command-specific handling of common response types

    def select_untagged_ok(self, response):
        if response.data.data and response.data.data[0] in \
            self._imapll.session.folder.__slots__:
            setattr(self._imapll.session.folder, response.data.data[0],
                    response.data.data[1])

        return self.untagged_ok(response)

    def select_tagged_ok(self, response):
        if response.data.data and response.data.data[0] == 'read-only':
            self._imapll.session.writable = False
        else:
            self._imapll.session.writable = True

        return self.untagged_ok(response)



