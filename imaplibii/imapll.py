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

'''This is an IMAP low level module, it provides the basic mechanisms
to connect to an IMAP server. It makes no attempt to parse the server responses.
The only processing made is striping the CRLF from the end of each line returned
by the server.

NOTES: This code is an adaptation of the original imaplib module code (the
standard python IMAP client module) by Piers Lauder.
'''

# Global imports
import socket, random, re, ssl
from threading import Timer
import pprint
from subprocess import PIPE, Popen
from platform import system

# Local imports
from utils import Int2AP, ContinuationRequests

# Constants

D_SERVER = 1        #: Debug responses from the server
D_CLIENT = 2        #: Debug data sent by the client
D_RESPONSE = 4      #: Debug obtained response

Debug = 0
#Debug = D_SERVER | D_CLIENT

MAXCOMLEN = 48      #: Max command len to store on the tagged_commands dict

IMAP4_PORT = 143    #: Default IMAP port
IMAP4_SSL_PORT = 993 #: Default IMAP SSL port
CRLF = '\r\n'

literal_re = re.compile('.*{(?P<size>\d+)}$')
send_literal_re = re.compile('.*{(?P<size>\d+)}\r\n')

class IMAP4(object):
    '''Bare bones IMAP client.

    This class implements a very simple IMAP client, all it does is to send
    strings to the server and retrieve the server responses.

    Features:

        - The literals sent from the server are treated the same way as any
          other element. For instance, if we request an envelope from a message,
          the server can represent the subject as a literal. The envelope
          response will be assembled as a single string.
        - The continuation requests are handled transparently with the help of
          the L{ContinuationRequests Class<ContinuationRequests>}.
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

    '''
    class Error(Exception):
        '''Logical errors - debug required'''
        pass
    class Abort(Exception):
        '''Service errors - close and retry'''
        pass
    class ReadOnly(Exception):
        '''Mailbox status changed to READ-ONLY'''
        pass

    def __init__(self, host, port=IMAP4_PORT, parse_command = None):
        # Connection
        self.host = host
        self.port = port

        # Create unique tag for this session,
        # and compile tagged response matcher.
        self.tagpre = Int2AP(random.randint(4096, 65535))
        self.tagre = re.compile(r'(?P<tag>'
                        + self.tagpre
                        + r'\d+) (?P<type>[A-Z]+) (?P<data>.*)')
        self.tagnum = 0

        self.tagged_commands = {}
        self.continuation_data = ContinuationRequests()

        # Open the connection to the server
        self.open( host, port )

        # State of the connection:
        self.state = 'LOGOUT'

        self.welcome = self._get_response()

        if parse_command:
            self.parse_command = parse_command
        else:
            self.parse_command = self.dummy_parse_command

        if 'PREAUTH' in self.welcome:
            self.state = 'AUTH'
        elif 'OK' in self.welcome:
            self.state = 'NONAUTH'
        else:
            raise self.Error(self.welcome)

    def _check_socket_alive(self, sock=None):
        '''
        Check if the socket is alive. Not sure this is necessary or useful.
        '''
        if not sock:
            sock = self.sock

        r = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)

    def _set_sock_keepalive(self, sock=None):
        '''
        Enable TCP layer 3 keepalive options on the socket.
        '''
        if not sock:
            sock = self.sock

        #Periodically probes the other end of the connection and terminates
        # if it's half-open.
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_KEEPALIVE,True)
        #Max number of keepalive probes TCP should send before dropping a
        # connection.
        sock.setsockopt(socket.SOL_TCP, socket.TCP_KEEPCNT, 3)
        #Time in seconds the connection should be idle before TCP starts
        # sending keepalive probes.
        sock.setsockopt(socket.SOL_TCP, socket.TCP_KEEPIDLE, 10)
        #Time in seconds between keepalive probes.
        sock.setsockopt(socket.SOL_TCP, socket.TCP_KEEPINTVL, 2)
        return sock

    def _open(self, host=None, port=None):
        if not host:
            host = self.host
        else:
            self.host = host
        if not port:
            port = self.port
        else:
            self.port = port

        resolv = socket.getaddrinfo(host, port, socket.AF_UNSPEC,
                                   socket.SOCK_STREAM)

        # Try each address returned by getaddrinfo in turn until we
        # manage to connect to one.
        last_error = 0
        for remote in resolv:
            af, socktype, proto, canonname, sa = remote
            sock = socket.socket(af, socktype, proto)
            last_error = sock.connect_ex(sa)
            if last_error == 0:
                break
            else:
                sock.close()

        if last_error != 0:
            raise socket.error(last_error)

        return sock

    def _read(self, size, read_from, rettype=str):
        """
        Abstracted version of read.
        Contains fixes for ssl and Darwin
        """
        # sslobj.read() sometimes returns < size bytes
        data = bytearray()
        read = 0
        if (system() == 'Darwin') and (size>0):
            # This is a hack around Darwin's implementation of realloc() (which
            # Python uses inside the socket code). On Darwin, we split the
            # message into 100k chunks, which should be small enough - smaller
            # might start seriously hurting performance ...
            # this is taken from OfflineIMAP
            to_read = lambda s,r: min(s-r,8192)
        else:
            to_read = lambda s,r: s-r
        while len(data) < size:
            #data = read_from.read(size-read)
            data.extend( read_from.read(to_read(size,read)) )
            #read = len(data)

        if type(data) is not rettype:
            data = rettype(data)
        return data

    ##
    # Overridable methods
    ##

    def open(self, host=None, port=None):
        '''Setup connection to remote server on "host:port"
        This connection will be used by the routines:
        L{read<read>}, L{readline<readline>}, L{send<send>},
        L{shutdown<shutdown>}.

        @param host: hostname to connect to (default: use host set during instantiation)

        @param port: port to connect to (default: use port set during instantiation)
        '''

        self.sock = self._open(host, port)
        self.file = self.sock.makefile('rb')

    def read(self, size):
        '''Read 'size' bytes from remote.'''
        if __debug__:
            if Debug & D_SERVER:
                print 'S: Read %d bytes from the server.' % size
        #Use the abstracted _read method for consistancy.
        #return self._read(size, self.file)
        return self.file.read(size)

    def readline(self):
        '''Read line from remote.'''
        line = self.file.readline()
        if not line:
            raise self.Abort('socket error: EOF')
        if __debug__:
            if Debug & D_SERVER:
                print 'S: %s' % line.replace(CRLF,'<cr><lf>')
        return line

    def send(self, data):
        '''Send data to remote.'''
        if __debug__:
            if Debug & D_CLIENT:
                print 'C: %s' % data.replace(CRLF,'<cr><lf>')
        try:
            self.sock.sendall(data)
        except (socket.error, OSError), val:
            raise self.abort('socket error: %s' % val)

    def shutdown(self):
        '''Close I/O established in "open".'''
        self.file.close()
        self.sock.close()

    def socket(self):
        '''
        Return socket instance used to connect to IMAP4 server.
        '''
        return self.sock

    def push_continuation( self, obj ):
        '''Insert a continuation in the continuation queue.

        @param obj: this parameter can be either a string, or a callable. If
        it's a string it will be poped unmodified when the next continuation
        is requested by the server. If it's a callable, the return from the
        callable will be sent to the server. The callable is called using the
        continuation data as argument.
        '''
        self.continuation_data.push( obj )

    ##
    # SEND/RECEIVE commands from the server
    ##

    def send_command(self, command, read_resp = True ):
        '''
        Send a command to the server:

            - Handles literals sent to teh server;
            - Updates the tags sent to the server (<instance>.tagged_commands);
            - <instance>.tagged_commands[tag] - contains the first MAXCOMLEN
              of the command;

        @param command: command to be sent to the server, without the tag and
        the final CRLF.
        @param read_resp: it true, automatically reads the server response.
        @type  read_resp: Boolean

        @return:
            - tag: the tag used on the sent command;
            - response from the server to the sent command (only if read_resp);
        '''
        tag = self._new_tag()

        # Do not store the complete command on tagged_commands
        if len(command) > MAXCOMLEN:
            tagcommand = command[:MAXCOMLEN] + ' ...'
        else:
            tagcommand = command

        # Check for a literal:
        lt = send_literal_re.search(command)
        if lt:
            # If there are any additional command arguments, the literal octets
            # are followed by a space and those arguments (from RFC3501 sec 7.5)
            self.continuation_data.push(command[lt.end():])
            command = command[:lt.end()-2]

        # Send the command to the server
        self.tagged_commands[tag] = tagcommand
        self.send('%s %s%s' % (tag, command, CRLF))

        if read_resp:
            return tag, self.read_responses(tag)
        else:
            return tag

    def _read_resp_loop(self, response):
        '''
        Modified read_responses loop meant for IDLE.

        The idea is to keep reading data from the server until we know we
        have all of the data that was requested by our last command.
        
        The problem with this is it doesn't quite work for IDLE notification.
        We want updates from IDLE to go into the dispatcher NOW, not 30 minutes
        later when we end IDLE mode.
        '''
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

    def _read_resp_loop1(self, loop_cond_chk, response):
        '''
        Generic read_responses loop.
        '''
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
            raise self.Error('Unknown response:\n%s' % resp)
        return response

    def read_responses(self, tag):
        '''
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
        L{parse_command<parse_command>}.
        '''
        response = { 'tagged' : {},
                     'untagged' : [] }

        response = self._read_resp_loop(response)

        if self.continuation_data:
            pprint.pprint(self.continuation_data)
        self.continuation_data.clear()

        if __debug__:
            if Debug & D_RESPONSE:
                print response

        return self.parse_command(tag, response)

    def dummy_parse_command(self, tag, response):
        '''Further processing of the server response.
        This method is called by L{read_responses<read_responses>}.

        @param tag: the tag used on the command.
        @param response: a server response on the format::

            response = { 'tagged' : {TAG001:{ 'status': ..., 'message': ...,
                         'command': ... }, ... },
                     'untagged' : [ '* 1st untagged', '* 2nd untagged', ... ] }

        @return: Since this is an abstract method, it only returns the fed
        response, unmodified.
        '''
        return response

    ##
    # Private methods
    ##
    def _new_tag(self):
        '''Returns a new tag.'''
        tag = '%s%03d' % (self.tagpre, self.tagnum)
        self.tagnum += 1
        return tag

    def _get_line(self):
        '''Gets a line from the server. If the line contains a literal in it,
        it will recurse until we have read a complete line.
        '''
        # Read a line from the server
        line = self.readline()[:-2]

        # Verify if a literal is comming
        lt = literal_re.match(line)
        if lt:
            # read 'size' bytes from the server and append them to
            # the line read and read the rest of the line
            size = int(lt.group('size'))
            literal = self.read(size)
            line += CRLF + literal + self._get_line()

        return line

    def _get_response(self):
        '''This method is called from within L{read_responses<read_responses>},
        it serves the purpose of making a broad classification of the server
        responses. The possibilities are:

            - It's a tagged response, the response will be encapsulated on a
              dict;
            - It's an untagged response, we return a string;
            - It's a continuation request, '+ <continuation data>CRLF', a
              continaution response will be poped from the continuation queue.
              If we don't have a prepared continuation, we'll try to cancel the
              command by sending a '*'.
        '''
        # Read a line from the server
        line = self._get_line()

        # Verify whether it's a tagged or untagged response:
        tg = self.tagre.match(line)
        if tg:
            # It's tagged
            tag = tg.group('tag')
            if not tag in self.tagged_commands:
                raise self.Abort('unexpected tagged response: %s' % line)
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
            self.send( self.continuation_data.pop(line[2:]) + CRLF )
            return None
        else:
            raise self.Abort('What now??? What\'s this:\nS: %s' % line)

class IMAP4_SSL(IMAP4):
    """IMAP4 client class over SSL connection

    Instantiate with: IMAP4_SSL([host[, port[, keyfile[, certfile]]]])

            host - host's name (default: localhost);
            port - port number (default: standard IMAP4 SSL port).
            keyfile - PEM formatted file that contains your private key (default: None);
            certfile - PEM formatted certificate chain file (default: None);

    for more documentation see the docstring of the parent class IMAP4.
    """
    def __init__(self, host,
        port = IMAP4_SSL_PORT,
        keyfile = None,
        certfile = None,
        parse_command=None):

        self.readbuf = bytearray()
        self.keyfile = keyfile
        self.certfile = certfile
        IMAP4.__init__(self, host=host, port=port, parse_command=parse_command)

    def open(self, host=None, port=None):
        """Setup connection to remote server on "host:port".
            (default: localhost:standard IMAP4 SSL port).
        This connection will be used by the routines:
            read, readline, send, shutdown.
        """
        self.sock = self._open(host, port)
        self.sslobj = ssl.wrap_socket(self.sock, self.keyfile, self.certfile)
        self.file = self.sslobj.makefile('rb')

    def bad_read(self, size, rettype=str):
        """Read 'size' bytes from remote."""
        if __debug__:
            if Debug & D_SERVER:
                print 'S: Read %d bytes from the server.' % size
        #data = self._read(size, self.sslobj, rettype=rettype)
        #return data
        return self.sslobj.read(size)

    def bad_readline(self, rettype=str):
        """Read line from remote."""
        while 1:
            self.readbuf.extend( self.read(1024, bytearray) )
            nlidx = self.readbuf.find('\n')
            if nlidx != -1:
                line = self.readbuf[:nlidx+1]
                del self.readbuf[:nlidx+1]
                if type(line) is not rettype:
                    line = rettype(line)
                if __debug__:
                    if Debug & D_SERVER:
                        print 'S: %s' % line.replace(CRLF,'<cr><lf>')
                return line

    def send(self, data):
        '''Send data to remote.'''
        if __debug__:
            if Debug & D_CLIENT:
                print 'C: %s' % data.replace(CRLF,'<cr><lf>')
        try:
            self.sslobj.sendall(data)
        except (socket.error, OSError), val:
            raise self.abort('socket error: %s' % val)

    def old_send(self, data):
        """Send data to remote."""
        # NB: socket.ssl needs a "sendall" method to match socket objects.
        if __debug__:
            if Debug & D_CLIENT:
                print 'C: %s' % data.replace(CRLF,'<cr><lf>')
        bytes = len(data)
        while bytes > 0:
            sent = self.sslobj.write(data)
            if sent == bytes:
                break    # avoid copy
            data = data[sent:]
            bytes = bytes - sent

    def shutdown(self):
        """Close I/O established in "open"."""
        self.sock.close()

    def socket(self):
        """Return socket instance used to connect to IMAP4 server.

        socket = <instance>.socket()
        """
        return self.sock

    def ssl(self):
        """Return SSLObject instance used to communicate with the IMAP4 server.

        ssl = <instance>.socket.ssl()
        """
        return self.sslobj

class IMAP4_stream(IMAP4):
    '''
    IMAP4 client class over a stream

    Instantiate with: IMAP4_stream(command)

    where "command" is a string that can be passed to os.popen2()

    for more documentation on the IMAP side of the class, see the docstring
    of the parent class IMAP4.
    '''

    def __init__(self, command, parse_command = None):
        self.command = command
        IMAP4.__init__(self, None, None, parse_command)

    def open(self, host = None, port = None):
        '''
        Setup a stream connection.
        This connection will be used by the routines:
            read, readline, send, shutdown.

        The host and port arguments are purely vestigial.
        '''
        self.host = None
        self.port = None
        self.file = None
        p = Popen(self.command, shell=True, stdin=PIPE, stdout=PIPE,
                          close_fds=True)
        self.writefile, self.readfile =  (p.stdin, p.stdout)
        self.sock = p

    def read(self, size):
        '''Read 'size' bytes from remote.'''
        if __debug__:
            if Debug & D_SERVER:
                print 'S: Read %d bytes from the server.' % size
        return self.readfile.read(size)

    def readline(self):
        '''Read line from remote.'''
        line = self.readfile.readline()
        if not line:
            raise self.Abort('socket error: EOF')
        if __debug__:
            if Debug & D_SERVER:
                print 'S: %s' % line.replace(CRLF,'<cr><lf>')
        return line

    def send(self, data):
        '''Send data to remote.'''
        if __debug__:
            if Debug & D_CLIENT:
                print 'C: %s' % data.replace(CRLF,'<cr><lf>')
        self.writefile.write(data)
        self.writefile.flush()

    def shutdown(self):
        '''Close I/O established in "open".'''
        self.readfile.close()
        self.writefile.close()
        try: self.sock.terminate()
        except: pass
        else:
            def do_kill():
                if self.sock.poll() is None:
                    self.sock.kill()

            tmr = Timer(15.0, do_kill)
            tmr.daemon = True
            tmr.start()



if __name__ == '__main__':
    import getopt, getpass, sys

    try:
        optlist, args = getopt.getopt(sys.argv[1:], 'd:s:')
    except getopt.error, val:
        optlist, args = (), ()

    Debug = D_SERVER | D_CLIENT | D_RESPONSE

    if not args: args = ('',)

    host = args[0]

    USER = getpass.getuser()
    PASSWD = getpass.getpass("IMAP password for %s on %s: " % (USER, host or "localhost"))

    M = IMAP4( host )

    M.send_command('LOGIN %s "%s"' % (USER, PASSWD))

    M.send_command('LOGOUT' )

