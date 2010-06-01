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
from errors import Error, Abort, ReadOnly, NotYet
from imapcommands import COMMANDS, EXEMPT_CMDS, STATUS

# Constants

D_SERVER = 1        #: Debug responses from the server
D_CLIENT = 2        #: Debug data sent by the client
D_RESPONSE = 4      #: Debug obtained response

Debug = 0
#Debug = D_SERVER | D_CLIENT

MAXCOMLEN = 48      #: Max command len to store on the tagged_commands dict

CRLF = '\r\n'

literal_re = re.compile('.*{(?P<size>\d+)}$')
send_literal_re = re.compile('.*{(?P<size>\d+)}\r\n')


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

    def __init__(self, transport, parse_command=None):
        # Create unique tag for this session,
        # and compile tagged response matcher.
        self.tagpre = Int2AP(random.randint(4096, 65535))
        self.tagre = re.compile(r'(?P<tag>'
                        + self.tagpre
                        + r'\d+) (?P<type>[A-Z]+) (?P<data>.*)')
        self.tagnum = 0

        self.tagged_commands = {}
        self.continuation_data = ContinuationRequests()

        self._state = deque(maxlen=3)
        self._state_lock = Lock()
        self._cmdque = deque()
        self._tagref = WeakValueDictionary()

        if parse_command:
            self.parse_command = parse_command
        else:
            self.parse_command = self.dummy_parse_command

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



    def push_continuation( self, obj ):
        """
        Insert a continuation in the continuation queue.

        :param obj: this parameter can be either a string, or a callable. If
        it's a string it will be poped unmodified when the next continuation
        is requested by the server. If it's a callable, the return from the
        callable will be sent to the server. The callable is called using the
        continuation data as argument.
        """
        self.continuation_data.append( obj )

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

    def dummy_parse_command(self, tag, response):
        """Further processing of the server response.
        This method is called by `read_responses`.

        @param tag: the tag used on the command.
        @param response: a server response on the format::

            response = { 'tagged' : {TAG001:{ 'status': ..., 'message': ...,
                         'command': ... }, ... },
                     'untagged' : [ '* 1st untagged', '* 2nd untagged', ... ] }

        @return: Since this is an abstract method, it only returns the fed
        response, unmodified.
        """
        return response

    def _new_tag(self):
        """Returns a new tag."""
        tag = '%s%03d' % (self.tagpre, self.tagnum)
        self.tagnum += 1
        return tag

    #TODO: redo the following methods

    def _get_line(self):
        """Gets a line from the server. If the line contains a literal in it,
        it will recurse until we have read a complete line.
        """
        # Read a line from the server
        line = self._transport.readline()[:-2]

        # Verify if a literal is comming
        lt = literal_re.match(line)
        if lt:
            # read 'size' bytes from the server and append them to
            # the line read and read the rest of the line
            size = int(lt.group('size'))
            literal = self._transport.read(size)
            line += CRLF + literal + self._get_line()

        return line

    def _get_response(self):
        """
        This method is called from within `read_responses`,
        it serves the purpose of making a broad classification of the server
        responses. The possibilities are:

            - It's a tagged response, the response will be encapsulated on a
              dict;
            - It's an untagged response, we return a string;
            - It's a continuation request, '+ <continuation data>CRLF', a
              continaution response will be poped from the continuation queue.
              If we don't have a prepared continuation, we'll try to cancel the
              command by sending a '*'.
        """
        # Read a line from the server
        line = self._get_line()

        # Verify whether it's a tagged or untagged response:
        tg = self.tagre.match(line)
        if tg:
            # It's tagged
            tag = tg.group('tag')
            if not tag in self.tagged_commands:
                raise Abort('unexpected tagged response: %s' % line)
            type = tg.group('type')
            data = tg.group('data')
            response = { 'status': type, 'message': data,
                         'tag': tag,
                         'command': self.tagged_commands[tag] }
            del self.tagged_commands[tag]
            return response
        elif self.state == 'IDLE':
            return line
        elif line[:2] == '* ':
            # It's untagged
            return line
        elif line[:2] == '+ ' or line == '+':
            # It's a continuation, we're sending a literal
            self._transport.write( self.continuation_data.send(line[2:]) + CRLF )
            return None
        else:
            raise Abort('What now??? What\'s this:\nS: %s' % line)

    def _idle_dispatch(self, response):
        try:
            return self.idle_dispatch(response)
        finally:
            response['tagged'].clear()
            del response['untagged'][:]

    def idle_dispatch(self, response):
        #TODO: replace the print statements below with NotImplemented exception.
        print 'Not implemented!'
        print '(got %s response tho, btw)' % str(response)

    def _read_resp_loop(self, response):
        """
        Modified read_responses loop meant for IDLE.

        The idea is to keep reading data from the server until we know we
        have all of the data that was requested by our last command.
        
        The problem with this is it doesn't quite work for IDLE notification.
        We want updates from IDLE to go into the dispatcher NOW, not 30 minutes
        later when we end IDLE mode.
        """
        data_release = None
        resp_buffer = { 'tagged' : {},
                        'untagged' : [] }

        while self.tagged_commands:
            # If we have responses to read we should get them
            # from the server up until there are no more responses
            resp = self._get_response()

            # This little gem is necessary for Exchange.
            # Unlike sane imap servers like Gmail, when something
            # is done to cause an IDLE notification to go off
            # Exchange isn't satisified with sending out just one
            # message, no! It has to send out 5 :(
            if self.state == 'IDLE':
                try: data_release.cancel()
                except AttributeError:
                    pass #quack!

            resp_buffer = self._build_read_resp(resp, resp_buffer)

            if self.state == 'IDLE':
                data_release = Timer(3, self._idle_dispatch, (resp_buffer,))
                            #TODO: may be interesting to do heuristics one day
                            # on the timer value so it can change to suit its env.
                data_release.start()

        response = resp_buffer
        return response

    def _read_resp_loop1(self, loop_cond_chk, response):
        """
        Generic read_responses loop.
        """
        while loop_cond_chk:
            # If we have responses to read we should get them
            # from the server up until there are no more responses
            resp = self._get_response()
            response = self._build_read_resp(resp, response)

        return response

    def _build_read_resp(self, resp, response):
        if isinstance(resp,str):
            response['untagged'].append(resp)
        elif isinstance(resp,dict):
            # A tagged response is dict formated
            response['tagged'][resp['tag']] = resp
        elif resp == None:
            # We've sent a continuation
            pass
        else:
            raise Error('Unknown response:\n%s' % resp)
        return response

    def read_responses(self, tag):
        """
        Reads the responses from the server.

        The rules followed are:

            - If the line starts with a "*" + SP it's an untagged response;
            - If the line ends with {<number>}CRLF it's an IMAP literal and
              on the same iteration of the loop the next <number> bytes from the
              server will be read;
            - If the line starts with '<tag> + SP' it's the end on a tagged
              response.

        The returned data is in the form::

            response = { 'tagged' : {TAG001:{ 'status': ..., 'message': ...,
                         'command': ... }, ... },
                     'untagged' : [ '* 1st untagged', '* 2nd untagged', ... ] }

        @param tag: the tag to read the response for. Please note that due the
        IMAP characteristics we can't predict the server response order. Because
        of this, it's possible to have in a single response severall tagged
        responses besides the tag we are asking the response for. In any case
        this method will stop reading from the server as soon as it has read the
        tagged response for the tag parameter.

        @return: Returns the server response filtred by
        `parse_command`.
        """
        response = { 'tagged' : {},
                     'untagged' : [] }

        response = self._read_resp_loop(response)

        assert not self.continuation_data, "still have leftover continuation data"

        logging.debug(response)
        if __debug__:
            if Debug & D_RESPONSE:
                print response

        return self.parse_command(tag, response)



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

