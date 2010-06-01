


import socket
import ssl
import logging
from cStringIO import StringIO
from platform import system
from subprocess import PIPE, Popen
from utils import min_ver_chk


from errors import Error, Abort, ReadOnly

IMAP_PORT = 143    #: Default IMAP port
IMAP_SSL_PORT = 993 #: Default IMAP SSL port
CRLF = '\r\n'

# If python version is not at least 2.5.3 then use the included compatability
# read method to prevent an obscure memory leak on some systems.
if min_ver_chk([2,5,3]):
    REQ_COMPAT_READ = 0
else:
    REQ_COMPAT_READ = 1


class stream(object):
    def __na(self):
        raise NotImplemented

    def close(self):
        return self._close()

    def read(self, size=-1):
        logging.debug('S: Read %d bytes from the server.' % size)
        return self._read(size)

    def readline(self):
        line = self._readline()
        logging.debug('S: %s' % line.replace(CRLF,'<cr><lf>'))
        return line

    def write(self, data):
        logging.debug('C: %s' % data.replace(CRLF,'<cr><lf>'))
        return self._write(data)

    def flush(self):
        return self._flush()

    close.__doc__ = file.close.__doc__
    flush.__doc__ = file.flush.__doc__
    read.__doc__ = file.read.__doc__
    readline.__doc__ = file.readline.__doc__
    write.__doc__ = file.write.__doc__

class tcp_stream(stream):
    def __init__(self, host, port=IMAP_PORT):
        self.sock = self._open(host, port)
        self.file = self.sock.makefile('rb')


    def _check_socket_alive(self, sock=None):
        """
        Check if the socket is alive. Not sure this is necessary or useful.
        """
        if not sock:
            sock = self.sock

        r = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        assert r is 0


    def _set_sock_keepalive(self, sock=None):
        """
        Enable TCP layer 3 keepalive options on the socket.
        """
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


    def _open(self, host, port):
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


    def _compat_read(self, size, read_from):
        """
        Abstracted version of read.
        Contains fixes for ssl and Darwin
        """
        # sslobj.read() sometimes returns < size bytes
        io = StringIO()
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
        while read < size:
            data = read_from.read(to_read(size,read))
            read += len(data)
            io.write(data)

        return io.getvalue()


    def _read(self, size):
        if REQ_COMPAT_READ:
            #malloc bug present in python prior to 2.5.3.
            return self._compat_read(size, self.file)
        else:
            return self.file.read(size)


    def _readline(self):
        line = self.file.readline()
        if not line:
            raise Abort('socket error: EOF')
        return line


    def _write(self, data):
        try:
            self.sock.sendall(data)
        except (socket.error, OSError), val:
            Abort('socket error: %s' % val)


    def _close(self):
        self.file.close()
        self.sock.close()



class ssl_stream(tcp_stream):
    """
    TCP transport stream over SSL.

    Instantiate with: IMAP4_SSL(host[, port[, keyfile[, certfile]]])

            host - host's name (default: localhost);
            port - port number (default: standard IMAP4 SSL port).
            keyfile - PEM formatted file that contains your private key (default: None);
            certfile - PEM formatted certificate chain file (default: None);
    """
    def __init__(self, host, port=IMAP_SSL_PORT, keyfile=None, certfile=None,
             ssl_version=ssl.PROTOCOL_SSLv3, do_handshake_on_connect=True):
        self.sock = ssl.wrap_socket(self._open(host, port), keyfile=keyfile,
                                    certfile=certfile, ssl_version=ssl_version,
                                    do_handshake_on_connect=do_handshake_on_connect)
        self.file = self.sock.makefile('rb')


    def do_handshake(self):
        self.sock.do_handshake()


    def unwrap(self):
        self.sock.unwrap()


    do_handshake.__doc__ = ssl.SSLSocket.do_handshake.__doc__
    unwrap.__doc__ = ssl.SSLSocket.unwrap.__doc__



class process_stream(stream):
    def open(self, command):
        """
        Setup a stream connection.
        This connection will be used by the routines:
            read, readline, send, shutdown.

        The host and port arguments are purely vestigial.
        """
        p = Popen(self.command, shell=True, stdin=PIPE, stdout=PIPE,
                          close_fds=True)
        self.writefile, self.readfile =  (p.stdin, p.stdout)
        self.sock = p

    def _read(self, size):
        return self.readfile.read(size)

    def _readline(self):
        line = self.readfile.readline()
        if not line:
            raise Abort('socket error: EOF')
        return line

    def _write(self, data):
        self.writefile.write(data)
        self.writefile.flush()

    def _close(self):
        self.readfile.close()
        self.writefile.close()
        self.sock.wait()

