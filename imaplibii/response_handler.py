

from weakref import proxy

from utils import command, null_handler
from imapcommands import AUTH, NONAUTH, SELECTED, LOGOUT
from errors import Error, Abort
import logging

nh = null_handler()
logger = logging.getLogger("imaplibii.response_handler")
logger.addHandler(nh)

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
        logger.debug('continuation - %r' % response)
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
        logger.debug('untagged_ok - %r' % response)
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
        logger.debug('untagged_no - %r' % response)
        raise NotImplemented

    def untagged_bad(self, response):
        """
        Indicates a protocol-level error for which the associated command can
        not be determined; it can also indicate an internal server failure.
        """
        logger.debug('untagged_bad - %r' % response)
        raise NotImplemented

    def untagged_bye(self, response):
        #FIXME need to continue reading until EOF
        logger.debug('untagged_bye - %r' % response)
        self._imapll.transport.close()
        self._imapll.state = LOGOUT

    def untagged_preauth(self, response):
        logger.debug('untagged_preauth - %r' % response)
        with self._imapll._state_lock:
            if self._imapll.state is LOGOUT:
                self._imapll.state = AUTH
                self._imapll.welcome = response

    def tagged_ok(self, response):
        logger.debug('tagged_ok - %r' % response)
        ccb = self._imapll._tagref[response.tag].completion_cb
        if ccb is not None:
            ccb(response)
        with self._imapll._state_lock:
            assert self._imapll.state == response.tag
            del self._imapll.state
        #XXX: check command queue for next command and send it
        #XXX: if command queue is empty, kill loop?

    def tagged_no(self, response):
        logger.debug('tagged_no - %r' % response)
        with self._imapll._state_lock:
            assert self._imapll.state == response.tag
            del self._imapll.state

        e = 'Encountered error running command. IMAP Server says: %s' % response.data
        raise Error(e)

    def tagged_bad(self, response):
        logger.debug('tagged_bad - %r' % response)
        with self._imapll._state_lock:
            assert self._imapll.state == response.tag
            del self._imapll.state

        e = 'Bad command. IMAP Server says: %s' % response.data
        raise Error(e)




    # Server and Mailbox Status Responses

    def untagged_capability(self, response):
        logger.debug('untagged_capability - %r' % response)
        raise NotImplemented

    def untagged_list(self, response):
        logger.debug('untagged_list - %r' % response)
        raise NotImplemented

    def untagged_lsub(self, response):
        logger.debug('untagged_lsub - %r' % response)
        raise NotImplemented

    def untagged_status(self, response):
        logger.debug('untagged_status - %r' % response)
        raise NotImplemented

    def untagged_search(self, response):
        logger.debug('untagged_search - %r' % response)
        raise NotImplemented

    def untagged_flags(self, response):
        logger.debug('untagged_flags - %r' % response)
        raise NotImplemented



    # Mailbox Size Responses

    def untagged_exists(self, response):
        logger.debug('untagged_exists - %r' % response)
        raise NotImplemented

    def untagged_recent(self, response):
        logger.debug('untagged_recent - %r' % response)
        raise NotImplemented



    # Message Status Responses

    def untagged_expunge(self, response):
        logger.debug('untagged_expunge - %r' % response)
        raise NotImplemented

    def untagged_fetch(self, response):
        logger.debug('untagged_fetch - %r' % response)
        cmd = self._imapll._tagref[self._imapll.state]
        cmd.responses.append(response)


    # command-specific handling of common response types

    def select_untagged_ok(self, response):
        logger.debug('select_untagged_ok - %r' % response)
        if response.data.data and response.data.data[0] in \
            self._imapll.session.folder.__slots__:
            setattr(self._imapll.session.folder, response.data.data[0],
                    response.data.data[1])

        return self.untagged_ok(response)

    def select_tagged_ok(self, response):
        logger.debug('select_tagged_ok - %r' % response)
        if response.data.data and response.data.data[0] == 'read-only':
            self._imapll.session.writable = False
        else:
            self._imapll.session.writable = True

        return self.untagged_ok(response)



