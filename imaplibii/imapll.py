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
from threading import Timer
from collections import deque
from weakref import WeakValueDictionary
from threading import Lock

# Local imports
from utils import Int2AP, ContinuationRequests
from parser import lexer_loop
from response_handler import response_handler
from errors import Error, Abort, ReadOnly, NotYet
from imapcommands import COMMANDS, EXEMPT_CMDS, STATUS
from imapcommands import AUTH, NONAUTH, SELECTED, LOGOUT

# Constants

Debug = 0

CRLF = '\r\n'


class imap_client(object):
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

    def __init__(self, transport, response_handler=response_handler, threaded=False):
        # Create unique tag for this session,
        # and compile tagged response matcher.
        self.tagpre = Int2AP(random.randint(4096, 65535))
        self.tagnum = 0

        self._response_runner = None
        self._state = deque(maxlen=3)
        self._state_lock = Lock()
        self._cmdque = deque()
        self._tagref = WeakValueDictionary()
        self.state = LOGOUT

        if threaded:
            self._dispatchque = deque()
        else:
            self._dispatchque = False

        self.response_handler = response_handler(self)


        # Connection to the server
        self._transport = transport

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
            self._response_runner = self._get_response(container=self._dispatchque)

        response = self._dispatchque.popleft()
        self.response_handler(response)



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
        tag = command.tag
        self._cmdque.append(command)
        self._tagref[tag] = command

        with self._state_lock:
            try:
                if self.state in COMMANDS[command.cmd]:
                    self.state = tag
                elif command.cmd not in EXEMPT_CMDS:
                    raise NotYet
                self._transport.write(command.format(tag))
            except NotYet: pass

        return command

    def _new_tag(self):
        """Returns a new tag."""
        tag = '%s%03d' % (self.tagpre, self.tagnum)
        self.tagnum += 1
        return tag






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

    Debug = D_SERVER | D_CLIENT | D_RESPONSE

    if not args: args = ('',)

    host = 'imap.gmail.com'

    USER = 'dom.lobue@gmail.com'
    PASSWD = getpass.getpass("IMAP password for %s on %s: " % (USER, host))

    M = IMAP4( ssl_stream( host ) )

    M.send_command('LOGIN %s "%s"' % (USER, PASSWD))

    pprint(M.send_command('LIST "" "*"'))

    M.send_command('LOGOUT' )

