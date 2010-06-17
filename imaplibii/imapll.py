# -*- coding: utf-8 -*-

# imaplib2 python module, meant to be a replacement to the python default
# imaplib module
# Copyright (C) 2008 Helder Guerreiro

## This file is part of imaplib2.
##
## imaplib2 is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## imaplib2 is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with hlimap.  If not, see <http://www.gnu.org/licenses/>.

#
# Helder Guerreiro <helder@paxjulia.com>
#
# $Id$
#

"""
This is an IMAP low level module, it provides the basic mechanisms
to connect to an IMAP server. It makes no attempt to parse the server responses.
The only processing made is striping the CRLF from the end of each line returned
by the server.

.. note::
    This code is an adaptation of the original imaplib module code (the
    standard python IMAP client module) by Piers Lauder.
"""

# stdlib imports
import random
import re
import logging
from threading import Timer, Thread
from collections import deque
from weakref import WeakValueDictionary
from threading import Lock

# Local imports
from utils import Int2AP, command
from parser import lexer_loop, scan_sexp, postparse
from response_handler import response_handler
from errors import Error, Abort, ReadOnly, NotYet
from imapcommands import COMMANDS, EXEMPT_CMDS, STATUS
from imapcommands import AUTH, NONAUTH, SELECTED, LOGOUT

# Constants

Debug = 0

CRLF = '\r\n'


class imapll(object):
    """
    Bare bones IMAP client.

    This class implements a very simple IMAP client, all it does is to send
    strings to the server and retrieve the server responses.

    Features:

        - The literals sent from the server are treated the same way as any
          other element. For instance, if we request an envelope from a message,
          the server can represent the subject as a literal. The envelope
          response will be assembled as a single string.
        - The continuation requests are handled transparently with the help of
          the `ContinuationRequests Class`.
        - The responses are encapsulated on a dictionary.

          For this conversation::

            C: OBOC0001 LOGOUT<cr><lf>
            S: * BYE LOGOUT received<cr><lf>
            S: OBOC0001 OK Completed<cr><lf>

          We get::

            {'untagged': ['* BYE LOGOUT received'],
             'tagged': {'OBOC0001': { 'status': 'OK',
                                      'message': 'Completed',
                                      'tag': 'OBOC0001',
                                      'command': 'LOGOUT'
            }}}

    It's very easy to transform this class so that we can send severall
    commands to the server in paralel. Maybe in the future we can
    implement this.

    Usage example::

        from imaplib2.imapll import IMAP4

        Debug = D_SERVER | D_CLIENT | D_RESPONSE

        M = IMAP4( host )
        tag, response = M.send_command('LOGIN %s "%s"' % ('user', 'some pass'))
        tag, response = M.send_command('CAPABILITY')
        tag, response = M.send_command('LOGOUT' )
    """

    def __init__(self, transport, response_handler=response_handler):
        # Create unique tag for this session,
        # and compile tagged response matcher.
        self.tagpre = Int2AP(random.randint(4096, 65535))
        self.tagnum = 0

        self.preparse = scan_sexp()
        self.preparse.next()
        self.postparse = staticmethod(postparse)

        self._response_runner = None
        self._state = deque(maxlen=3)
        self._state_lock = Lock()
        self._cmdque = deque()
        self._tagref = WeakValueDictionary()
        self.state = LOGOUT


        self.response_handler = response_handler(self)


        # Connection to the server
        self.transport = transport



        self.welcome = self._get_response()

        if 'PREAUTH' in self.welcome:
            self.state = 'AUTH'
        elif 'OK' in self.welcome:
            self.state = 'NONAUTH'
        else:
            raise Error(self.welcome)

    

    _state_set = lambda x,y: x._state.append(y)
    _state_get = lambda x: x._state[-1]
    _state_del = lambda x: x._state.pop()
    state = property(_state_get, _state_set, _state_del, "This is the state property.")

    _get_response = lexer_loop

    def get_response(self):
        if self._response_runner is None:
            self._response_runner = self._get_response()

        try:
            return self._response_runner.next()
        except StopIteration:
            self._response_runner = None
            raise Error



    def _init_lexer_loop(self, container=False):
        t = Thread(target=lexer_loop, args=(self,), kwargs={'container':container})
        t.daemon = True
        t.start()
        return t

    def _get_response2(self):
        if self._response_runner is None:
            self._response_runner = self._init_lexer_loop(container=self._dispatchque)
            #self._response_runner = self._get_response(container=self._dispatchque)

        response = self._dispatchque.popleft()
        return self.response_handler(response)



    # SEND/RECEIVE commands from the server

    def send_command(self, command):
        """
        Send a command to the server:

            - Handles literals sent to the server
            - Updates the tags sent to the server (<instance>.tagged_commands);
            - <instance>.tagged_commands[tag] - contains the first MAXCOMLEN
              of the command;

        :param command: command to be sent to the server, without the tag and
        the final CRLF.
        :param read_resp: it true, automatically reads the server response.
        :type  read_resp: Boolean

        :returns::
            - tag: the tag used on the sent command;
            - response from the server to the sent command (only if read_resp);
        """
        self._cmdque.append(command)

        with self._state_lock:
            if (self.state not in COMMANDS[command.cmd] and
                    command.cmd not in EXEMPT_CMDS):
                return
            cmd = command.format(self)
            tag = command.tag
            self._tagref[tag] = command
            self.state = tag
            self._transport.write(cmd)

        return command.responses

    def _new_tag(self):
        """Returns a new tag."""
        tag = '%s%03d' % (self.tagpre, self.tagnum)
        self.tagnum += 1
        return tag



class imap_client(imapll):


    # Any State

    def capability(self):
        """
      The CAPABILITY command requests a listing of capabilities that the
      server supports.
        """
        cmd = 'capability'
        return command(cmd)

    def logout(self):
        """
      The LOGOUT command informs the server that the client is done with
      the connection.
        """
        cmd = 'logout'
        return command(cmd)

    def noop(self):
        """
      The NOOP command always succeeds.  It does nothing.
        """
        cmd = 'noop'
        return command(cmd)

    
    # Not Authenticated State

    def authenticate(self, auth_type, auth_handler):
        """
      The AUTHENTICATE command indicates a [SASL] authentication
      mechanism to the server.  If the server supports the requested
      authentication mechanism, it performs an authentication protocol
      exchange to authenticate and identify the client.  It MAY also
      negotiate an OPTIONAL security layer for subsequent protocol
      interactions.
        """
        cmd = 'authenticate'
        return command(cmd, auth_type, continuation=auth_handler)

    def login(self, username, password):
        """
      The LOGIN command identifies the client to the server and carries
      the plaintext password authenticating this user.
        """
        cmd = 'login'
        args = '%s %s' % (username, password)
        return command(cmd, args)

    def starttls(self):
        """
        """
        cmd = 'starttls'
        return command(cmd)

    
    # Authenticated State

    def append(self, mailbox, message, flags=(), date=None):
        """
          The APPEND command appends the literal argument as a new message
          to the end of the specified destination mailbox.
        """
        cmd = 'append'
        size = len(message)
        flags = ' '.join(flags)
        date = (date and ' "%s"' % date) or ''
        args = '%s (%s)%s {%i}' % (mailbox, flags, date, size)
        return command(cmd, args, continuation=message)

    def status(self, mailbox, messages=False, recent=False, uidnext=False,
                uidvalidity=False, unseen=False):
        """
          The STATUS command requests the status of the indicated mailbox.
          It does not change the currently selected mailbox, nor does it
          affect the state of any messages in the queried mailbox (in
          particular, STATUS MUST NOT cause messages to lose the \Recent
          flag).
        """
        cmd = 'status'
        kwargs = {'messages': messages,
                  'recent': recent,
                  'uidnext': uidnext,
                  'uidvalidity': uidvalidity,
                  'unseen': unseen}
        kwargs = ( k for k,v in kwargs if v is True )
        args = '%s (%s)' % (mailbox, ' '.join(kwargs))
        return command(cmd, args)

    def list(self, reference="", mailbox=""):
        """
          The LIST command returns a subset of names from the complete set
          of all names available to the client.  Zero or more untagged LIST
          replies are returned, containing the name attributes, hierarchy
          delimiter, and name; see the description of the LIST reply for
          more detail.
        """
        cmd = 'list'
        args = '"%s" "%s"' % (reference, mailbox)
        return command(cmd, args)

    def lsub(self, reference="", mailbox=""):
        """
          The LSUB command returns a subset of names from the set of names
          that the user has declared as being "active" or "subscribed".
          Zero or more untagged LSUB replies are returned.
        """
        cmd = 'lsub'
        args = '"%s" "%s"' % (reference, mailbox)
        return command(cmd, args)

    def rename(self, oldname, newname):
        """
      The RENAME command changes the name of a mailbox.  A tagged OK
      response is returned only if the mailbox has been renamed.  It is
      an error to attempt to rename from a mailbox name that does not
      exist or to a mailbox name that already exists.
        """
        cmd = 'rename'
        args = '"%s" "%s"' % (oldname, newname)
        return command(cmd, args)

    def select(self, mailbox):
        """
      The SELECT command selects a mailbox so that messages in the
      mailbox can be accessed. 
        """
        cmd = 'select'
        return command(cmd, mailbox)

    def examine(self, mailbox):
        """
      The EXAMINE command is identical to SELECT and returns the same
      output; however, the selected mailbox is identified as read-only.
      No changes to the permanent state of the mailbox, including
      per-user state, are permitted; in particular, EXAMINE MUST NOT
      cause messages to lose the \Recent flag.
        """
        cmd = 'examine'
        return command(cmd, mailbox)

    def create(self, mailbox):
        """
      The CREATE command creates a mailbox with the given name.  An OK
      response is returned only if a new mailbox with that name has been
      created.  It is an error to attempt to create INBOX or a mailbox
      with a name that refers to an extant mailbox.
        """
        cmd = 'create'
        return command(cmd, mailbox)

    def delete(self, mailbox):
        """
      The DELETE command permanently removes the mailbox with the given
      name.  A tagged OK response is returned only if the mailbox has
      been deleted.  It is an error to attempt to delete INBOX or a
      mailbox name that does not exist.
        """
        cmd = 'delete'
        return command(cmd, mailbox)

    def subscribe(self, mailbox):
        """
      The SUBSCRIBE command adds the specified mailbox name to the
      server's set of "active" or "subscribed" mailboxes as returned by
      the LSUB command.
        """
        cmd = 'subscribe'
        return command(cmd, mailbox)

    def unsubscribe(self, mailbox):
        """
      The UNSUBSCRIBE command removes the specified mailbox name from
      the server's set of "active" or "subscribed" mailboxes as returned
      by the LSUB command.
        """
        cmd = 'unsubscribe'
        return command(cmd, mailbox)


    # Selected State

    def check(self):
        """
          The CHECK command requests a checkpoint of the currently selected
          mailbox.  A checkpoint refers to any implementation-dependent
          housekeeping associated with the mailbox (e.g., resolving the
          server's in-memory state of the mailbox with the state on its
          disk) that is not normally executed as part of each command.
        """
        cmd = 'check'
        return command(cmd)

    def close(self):
        """
          The CLOSE command permanently removes all messages that have the
          \Deleted flag set from the currently selected mailbox, and returns
          to the authenticated state from the selected state.
        """
        cmd = 'close'
        return command(cmd)

    def expunge(self):
        """
          The EXPUNGE command permanently removes all messages that have the
          \Deleted flag set from the currently selected mailbox.
        """
        cmd = 'expunge'
        return command(cmd)

    def search(self, *args):
        """
          The SEARCH command searches the mailbox for messages that match
          the given searching criteria.  Searching criteria consist of one
          or more search keys.
        """
        cmd = 'search'
        args = ' '.join(args)
        return command(cmd, args)

    def store(self, messages, flags=(), modify=None, verbose=False, use_uid=False):
        """
          The STORE command alters data associated with a message in the
          mailbox.  Normally, STORE will return the updated value of the
          data with an untagged FETCH response.  A suffix of ".SILENT" in
          the data item name prevents the untagged FETCH, and the server
          SHOULD assume that the client has determined the updated value
          itself or does not care about the updated value.
        """
        cmd = 'store'
        cmd = use_uid and 'uid %s' % cmd or cmd
        v = verbose and '' or '.silent'
        if modify is True: m = '+'
        elif modify is False: m = '-'
        else: m = ''
        flags = ' '.join(flags)
        args = '%s %sflags%s (%s)' % (messages, m, v, flags)
        return command(cmd, args)

    def _fetch(self, messages, use_uid=False, **terms):
        """
          The FETCH command retrieves data associated with a message in the
          mailbox.  The data items to be fetched can be either a single atom
          or a parenthesized list.
        """
        cmd = 'fetch'
        cmd = use_uid and 'uid %s' % cmd or cmd
        args = '(%s)' % ' '.join(( '%s%s' % s for s in terms.iteritems())).upper()
        return command(cmd, args)

    def copy(self, messages, folder, use_uid=False):
        """
          The COPY command copies the specified message(s) to the end of the
          specified destination mailbox.  The flags and internal date of the
          message(s) SHOULD be preserved, and the Recent flag SHOULD be set,
          in the copy.
        """
        cmd = 'copy'
        cmd = use_uid and 'uid %s' % cmd or cmd
        args = '%s %s' % (messages, folder)
        return command(cmd, args)






if __name__ == '__main__':
    import cgitb
    cgitb.enable(format='txt')
    import getopt, getpass, sys
    from pprint import pprint
    from imaplibii.transports import tcp_stream, ssl_stream

    try:
        optlist, args = getopt.getopt(sys.argv[1:], 'd:s:')
    except getopt.error, val:
        optlist, args = (), ()

    if not args: args = ('',)

    host = 'imap.gmail.com'

    USER = 'dom.lobue@gmail.com'
    PASSWD = getpass.getpass("IMAP password for %s on %s: " % (USER, host))

    M = imapll( ssl_stream( host ) )

    M.send_command('LOGIN %s "%s"' % (USER, PASSWD))

    pprint(M.send_command('LIST "" "*"'))

    M.send_command('LOGOUT' )

