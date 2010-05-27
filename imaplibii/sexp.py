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

# Global imports
import re, string

# Regexp
literal_re = re.compile(r'^{(\d+)}\r\n')
simple_re = re.compile(r'^([^ ()\[]+\[[^\]]+\]|[^ ()]+)')
quoted_re = re.compile(r'^"((?:[^"\\]|\\")*?)"')

# Errors
class SError(Exception): pass

def scan_sexp(text):
    '''S-Expression scanner.

    This is a non-recursive version. It uses the lists property of assigning
    only by reference to assemble the s-exp.

    @param text: text to be scanned.
    @type  text: s-exp string

    @return result: s-exp in a python list.
    '''

    # Initialization
    pos = 0
    lenght = len(text)
    current = ''
    result = []
    cur_result = result
    level = [ cur_result ]

    # Scanner
    while pos < lenght:

        # Quoted literal:
        if text[pos] == '"':
            quoted = quoted_re.match(text[pos:])
            if quoted:
                cur_result.append( quoted.groups()[0] )
                pos += quoted.end() - 1

        # Numbered literal:
        elif text[pos] == '{':
            lit = literal_re.match(text[pos:])
            if lit:
                 start = pos+lit.end()
                 end = pos+lit.end()+int(lit.groups()[0])
                 pos = end - 1
                 cur_result.append( text[ start:end ] )

        # Simple literal
        elif text[pos] not in '() ':
            simple = simple_re.match(text[pos:])
            if simple:
                tmp = simple.groups()[0]
                if tmp.isdigit():
                    tmp = int(tmp)
                elif tmp == 'NIL':
                    tmp = None
                cur_result.append( tmp )
                pos += simple.end() - 1

        # Level handling, if we find a '(' we must add another list, if we
        # find a ')' we must return to the previous list.
        elif text[pos] == '(':
            cur_result.append([])
            cur_result = cur_result[-1]
            level.append(cur_result)

        elif text[pos] == ')':
            try:
                cur_result = level[-2]
                del level[-1]
            except IndexError:
                raise SError('Unexpected parenthesis at pos %d' % pos)

        pos += 1

    return result

if __name__ == '__main__':
    from time import time

    count = 1000
    text = '(A NIL {5}\r\n12345 (D E))(F G)'
    text = '266 FETCH (FLAGS (\Seen) UID 31608 INTERNALDATE "30-Jan-2008 02:48:01 +0000" RFC822.SIZE 4509 ENVELOPE ("Tue, 29 Jan 2008 14:00:24 +0000" "Aprenda as tXcnicas e os truques da cozinha mais doce..." (("Ediclube" NIL "ediclube" "sigmathis.info")) (("Ediclube" NIL "ediclube" "sigmathis.info")) ((NIL NIL "ediclube" "sigmathis.info")) ((NIL NIL "helder" "example.com")) NIL NIL NIL "<64360f85d83238281a27b921fd3e7eb3@localhost.localdomain>"))'
    #text = 'AA 12341 NIL (A NIL "asdasd fffff\\"sdasd" {%d}\r\n%s (D E))(F G)' % ( count, '#' * count)
    #text = 'A B (C NIL (D E))(F G)'
    #text = '99 FETCH (UID 100 RFC822.SIZE 2260 INTERNALDATE "26-Oct-2004 04:35:14 +0000" FLAGS (\Seen) BODY[HEADER.FIELDS (Message-ID)] {54}%s%s)' % ( '\r\n', 'S' * 54 )
    text = '* 69 FETCH (UID 152132 FLAGS (\Seen) INTERNALDATE " 1-Feb-2010 17:14:13 -0700" RFC822.SIZE 994 BODY[HEADER.FIELDS (Message-ID)] {86}\r\nMessage-ID: <DC39B2A54BA9FF409E5BE5A51D4AE1FE0C6ED2DB@Exchange2k3.corp.stamps.com>\r\n\r\n)\r\n'
    text = '* 69 FETCH (INTERNALDATE " 1-Feb-2010 17:14:13 -0700" FLAGS (\Seen) UID 152132 BODY[HEADER.FIELDS (Message-ID)] {86}\r\nMessage-ID: <DC39B2A54BA9FF409E5BE5A51D4AE1FE0C6ED2DB@Exchange2k3.corp.stamps.com>\r\n\r\n RFC822.SIZE 994)\r\n'
    text = '* LIST (\Marked \HasNoChildren) "/" "Public Folders/Marketing/Archives/E-Commerce/Ecommerce Web Leads/Affiliates/Auction Sites/tradenswap"\r\n'
    text = '* 69 FETCH (INTERNALDATE " 1-Feb-2010 17:14:13 -0700" FLAGS (\Seen) UID 152132 BODY[HEADER.FIELDS.NOT (Message-ID)] {703}\r\nX-MimeOLE: Produced By Microsoft Exchange V6.5\r\nReceived: by Exchange2k3.corp.stamps.com\r\n.id <01CAA39C.A686F823@Exchange2k3.corp.stamps.com>; Mon, 1 Feb 2010 17:14:13 -0700\r\nMIME-Version: 1.0\r\nContent-Type: text/plain;\r\n.charset="us-ascii"\r\nContent-Transfer-Encoding: quoted-printable\r\nContent-class: urn:content-classes:message\r\nSubject: Feb 01, 2010 Generator Test\r\nDate: Mon, 1 Feb 2010 17:14:18 -0700\r\nX-MS-Has-Attach: \r\nX-MS-TNEF-Correlator: \r\nThread-Topic: Feb 01, 2010 Generator Test\r\nThread-Index: AcqjnKk8C1ctyOJ4QJabDqERnAg9Wg==\r\nFrom: "Benjamin Pak-To Siu" <bsiu@stamps.com>\r\nTo: "Data Center Operations" <DCO@Stamps.com>,\r\n."PCI" <PCI@stamps.com>,\r\n."Steve Spring" <Sspring@Stamps.com>\r\n\r\n RFC822.SIZE 994)\r\n'


    itx = 1000
    rit = xrange(itx)

    print 'Test to the s-exp parser:'
    print

    print 'Non Recursive (%d times):' % itx
    a = time()
    for i in rit:
        scan_sexp(text)
    b = time()
    print 1000 * (b-a) / itx, 'ms/iter'
    print itx, ' --> ', 1000 * (b-a) , 'ms'
    print
    print scan_sexp(text)
