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

"""Utility functions for the imaplibii module."""


# Global imports
import time, datetime
import re
from sys import exc_info
from collections import deque
from types import GeneratorType, FunctionType
from email.header import decode_header
from platform import python_version
from imaplibii.errors import NotAvailable

CRLF = '\r\n'

# Utility functions
def min_ver_chk(minver):
    """
    Ensure that the version of python running meets at least version `minver`.

    >>> platform.python_version()
    '2.3.4'
    >>> min_ver_chk([2, 5, 3])
    0
    >>> platform.python_version()
    '2.5.3'
    >>> min_ver_chk([2, 5, 3])
    1
    >>> platform.python_version()
    '2.6.4'
    >>> min_ver_chk([2, 5, 3])
    2

    :param minver: Minimum version of python required.
    :type minver: list of integers.
    :returns: a positive integer if successful.
    """
    pyv = python_version()
    pyv = map(int, pyv.split('.'))

    def vercmp(x):
        if pyv[x] > minver[x]:
            return 2
        elif pyv[x] < minver[x]:
            return 0

    for x in xrange(min(len(pyv), len(minver))):
        r = vercmp(x)
        if r: return 2 #success, exit early
        elif r is 0: return 0 #fail
    return 1 #just barely meets the reqs.


def getUnicodeHeader( header ):
    """Returns an unicode string with the content of the header string."""
    if not header: return ''

    # Decode the header:
    header_list = []

    for header in decode_header(header):
        if not header[1]:
            codec = 'iso-8859-1'
        else:
            codec = header[1]

        try:
            text = unicode(header[0], codec).encode('utf-8')
        except:
            try:
                text = unicode(header[0], 'iso-8859-1').encode('utf-8')
            except:
                raise

        header_list.append(text)

    return ' '.join(header_list)

def getUnicodeMailAddr( address_list ):
    """Return an address list with the mail addresses"""
    if not isinstance(address_list,list):
        return []

    # Verify the encoding:
    return [ (unquote(getUnicodeHeader(Xi[0])),'%s@%s' % (Xi[2],Xi[3]))
             for Xi in address_list ]


def Int2AP(num):
    """Convert integer to A-P string representation."""
    val = ''; AP = 'ABCDEFGHIJKLMNOP'
    num = int(abs(num))
    while num:
        num, mod = divmod(num, 16)
        val = AP[mod] + val
    return val



def makeTagged(t):
    """Composes a string with the tagged response"""
    r = '\nStatus: %(status)s\nMessage: %(message)s\nCommand: %(command)s' % t
    return r


def unquote( string ):
    if len(string) > 0:
        if string[0] == string[-1] == '"' or \
           string[0] == string[-1] == '\'':
            return string[1:-1]
    return string



Mon2num = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}

InternalDate = re.compile(
r'(?P<day>[ 0123][0-9])-(?P<mon>[A-Z][a-z][a-z])-(?P<year>[0-9][0-9][0-9][0-9])'
    r' (?P<hour>[0-9][0-9]):(?P<min>[0-9][0-9]):(?P<sec>[0-9][0-9])'
    r' (?P<zonen>[-+])(?P<zoneh>[0-9][0-9])(?P<zonem>[0-9][0-9])'
    )

EnvelopeDate = re.compile(r'(?:(?P<week_day>[A-Z][a-z][a-z]), )?(?P<day>[ \d][0-9]?) '
     r'(?P<month>[A-Z][a-z][a-z]) (?P<year>[0-9][0-9][0-9][0-9]) '
     r'(?P<hour>[0-9][0-9]):(?P<min>[0-9][0-9]):(?P<sec>[0-9][0-9]) '
     r'(?P<zonen>[-+])(?P<zoneh>[0-9][0-9])(?P<zonem>[0-9][0-9]).*'
    )

def envelopedate2datetime(resp):
    """
    Convert an envelope date to tuple

    :returns: Python time module tuple.
    """
    if not resp:
        return datetime.datetime.fromtimestamp(0)

    mo = EnvelopeDate.match(resp)

    if not mo:
        return datetime.datetime.fromtimestamp(0)

    try:
        mon = Mon2num[mo.group('month')]
    except:
        return datetime.datetime.fromtimestamp(0)
    zonen = mo.group('zonen')

    day = int(mo.group('day'))
    year = int(mo.group('year'))
    hour = int(mo.group('hour'))
    min = int(mo.group('min'))
    sec = int(mo.group('sec'))
    zoneh = int(mo.group('zoneh'))
    zonem = int(mo.group('zonem'))

    # INTERNALDATE timezone must be subtracted to get UT

    zone = (zoneh*60 + zonem)*60
    if zonen == '-':
        zone = -zone

    tt = (year, mon, day, hour, min, sec, -1, -1, -1)

    try:
        utc = time.mktime(tt)
    except:
        return datetime.datetime.fromtimestamp(0)

    # Following is necessary because the time module has no 'mkgmtime'.
    # 'mktime' assumes arg in local timezone, so adds timezone/altzone.

    lt = time.localtime(utc)
    if time.daylight and lt[-1]:
        zone = zone + time.altzone
    else:
        zone = zone + time.timezone

    return datetime.datetime.fromtimestamp(utc - zone)



def Internaldate2tuple(resp):
    """
    Convert IMAP4 INTERNALDATE to UT.

    :returns: Python time module tuple.
    """
    mo = InternalDate.match(resp)
    if not mo:
        return None

    mon = Mon2num[mo.group('mon')]
    zonen = mo.group('zonen')

    day = int(mo.group('day'))
    year = int(mo.group('year'))
    hour = int(mo.group('hour'))
    min = int(mo.group('min'))
    sec = int(mo.group('sec'))
    zoneh = int(mo.group('zoneh'))
    zonem = int(mo.group('zonem'))

    # INTERNALDATE timezone must be subtracted to get UT

    zone = (zoneh*60 + zonem)*60
    if zonen == '-':
        zone = -zone

    tt = (year, mon, day, hour, min, sec, -1, -1, -1)

    utc = time.mktime(tt)

    # Following is necessary because the time module has no 'mkgmtime'.
    # 'mktime' assumes arg in local timezone, so adds timezone/altzone.

    lt = time.localtime(utc)
    if time.daylight and lt[-1]:
        zone = zone + time.altzone
    else:
        zone = zone + time.timezone

    return time.localtime(utc - zone)



def shrink_fetch_list( msg_list ):
    """
    Shrinks the message list to use on the fetch command, consecutive msg_list
    numbers will be converted to first:last.

    :param msg_list: a list of message numbers or uids
    :type msg_list: list

    :returns: a list with the shrinked msg_list
    """
    tmp = []
    msg_list = list(msg_list)
    msg_list.sort()
    last = msg_list[0]
    anchor = 0

    for msgn in msg_list[1:]:
        if (last + 1) == msgn and not anchor:
            anchor = last
        elif anchor:
            if (last + 1) != msgn:
                if (anchor + 1) != last:
                    tmp.append( '%d:%d' % (anchor, last) )
                else:
                    tmp.append( '%d' % anchor )
                    tmp.append(  '%d' % last )
                anchor = 0
        else:
            tmp.append( last )

        last = msgn

    if anchor:
        if (anchor + 1) != last:
            tmp.append( '%d:%d' % (anchor, last) )
        else:
            tmp.append( '%d' % anchor )
            tmp.append( '%d' % last )
    else:
        tmp.append( '%d' % last )

    return tmp



def auth_ntlm(username, password, domain):
    try: from ntlm import ntlm
    except ImportError:
        raise NotAvailable
    def response(challenge):
        if challenge.startswith('+ '):
            challenge = challenge[2:]
        (ServerChallenge, NegotiateFlags) = \
                                ntlm.parse_NTLM_CHALLENGE_MESSAGE(challenge)
        return ntlm.create_NTLM_AUTHENTICATE_MESSAGE(ServerChallenge,
                                                username, domain, password,
                                                NegotiateFlags)
    init = ntlm.create_NTLM_NEGOTIATE_MESSAGE(username)
    return init, response


# Classes


class ContinuationRequests(deque):
    """
    Class to be used with the continuation requests made by the server.
    This is a deque for efficient append/pop operations on either side.
    
    Use the next method to get the next response in line.

    """
    def send(self, arg):
        return self._cointeract('send', arg)

    def next(self):
        return self._cointeract('next')

    def throw(self, typ, val=None, tb=None):
        return self._cointeract('throw', typ, val, tb)

    send.__doc__ = GeneratorType.send.__doc__
    next.__doc__ = GeneratorType.next.__doc__
    throw.__doc__ = GeneratorType.throw.__doc__
    put = deque.append

    def _cointeract(self, action, *args, **kwargs):
        """
        Actually runs the desired method with the appropriate args
        on the generator. This is based on the command dispatch pattern.
        """
        try: return getattr(self._runner, action)(*args, **kwargs)
        except (AttributeError, StopIteration):
            #either the trampoline schedular was left in a stopped state
            #the last time it was used, or it has never been used.
            self._runner = self._trampoline()
            return getattr(self, action)(*args)
        except IndexError: # Empty list
            return '*'

    def _trampoline(self):
        """
        This is a trampoline scheduler. It goes through each item
        stored in the deque and if the item turns out to be a generator,
        iterate through the generators items. If the generator yields a nother
        generator, put the first generator at the top of the queue, and iterate 
        through the new generator. When a generator is depleted of all items,
        switch get another item from the deque.
        """
        t, v = None, None
        while 1:
            n = self.popleft()
            if type(n) is FunctionType:
                if v is not None:
                    n = n(v)
                    v = None
                else:
                    n = n()
            if type(n) is GeneratorType:
                while 1:
                    try:
                        if v is not None:
                            assert t is None
                            x = n.send(v)
                            v = None
                        elif t is not None:
                            #we were thrown an exception
                            x = n.throw(*t)
                            del t #just to be safe: python documentation warns
                                  #that the traceback return value can create a
                                  #circular reference.
                            t = None
                        else:
                            x = n.next()
                    except StopIteration:
                        break
                    if type(x) is FunctionType:
                        x = x()
                    if type(x) is GeneratorType:
                        self.appendleft(n)
                        n = x
                        continue
                    try: v = ( yield x )
                    except:
                        t = exc_info()
                continue
            v = ( yield n )



class Command(object):
    def __init__(self, cmd, *args, **kwargs):
        self.cmd = cmd
        self.args = args
        self.kwargs = kwargs
        self.continuation = None
        self.finish = None

    def format(self, tag):
        if not self.args:
            return ' '.join((tag, self.cmd, CRLF))
        return ' '.join((tag, self.cmd, self.args, CRLF))

