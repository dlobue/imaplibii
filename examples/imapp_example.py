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

'''Example usage of imaplib2.imapll
'''

import imaplibii.imapp

from threading import Timer
import time

imaplibii.imapp.imapll.Debug = 3

if __name__ == '__main__':
    import getopt, getpass, sys, pprint

    try:
        optlist, args = getopt.getopt(sys.argv[1:], 'd:s:')
    except getopt.error, val:
        optlist, args = (), ()

    if not args: args = ('',)

    host = args[0]

    USER = 'dom.lobue@gmail.com'
    #USER = getpass.getuser()
    PASSWD = getpass.getpass("IMAP password for %s on %s: " % (USER, host or "localhost"))

    t = time.time()
    M = imaplibii.imapp.IMAP4P( host, ssl = True)

    def do_done():
        print 'trying do_done'
        pprint.pprint(M.done())
        #M.state = 'SELECTED'

    pprint.pprint(M.login(USER, PASSWD))

    pprint.pprint(M.list('INBOX'))
    pprint.pprint(M.select('INBOX'))

    pprint.pprint( M.capabilities)

    mt = Timer(60, do_done)
    mt.start()

    #M.state = 'IDLE'

    pprint.pprint(M.idle())

    pprint.pprint(M.logout())
    t = time.time() - t
    print 'total time taken = %s seconds' % t

