import cgitb
cgitb.enable(format='text')

from collections import deque, namedtuple
from cStringIO import StringIO

DOWN = '[('
UP = ')]'
DQUOTE = '"'
LS_DN = '{'
LS_UP = '}'
NIL = intern('NIL')

result_container_type = list

need_more = namedtuple('need_more', 'results transportmethod args')
token_tree = namedtuple('token_tree', 'results')

def updn_sep(text):
    for c in UP+DOWN+DQUOTE:
        w = ' %s ' % c
        text = text.replace(c,w)
    return text

def scan_sexp_orig(textchunk, result=None):

    result = deque()
    cur_result = deque()
    result.append(cur_result)
    quoted = deque()
    
    if type(textchunk) is not bytearray:
        textchunk = bytearray(textchunk)
    chunklist = deque( textchunk.splitlines(True) )
    #chunklist = deque( textchunk.split('\r\n', 1) )
    text = chunklist.popleft()

    #textlist = deque(map(nil_to_none, text.split()))
    text = str(updn_sep(text))
    textlist = deque(text.split())
    
    while 1:
        try: atom = textlist.popleft()
        except IndexError:
            if len(result) > 1:
                try:
                    text = chunklist.popleft()
                    text = str(updn_sep(text))
                    #text = str(text)
                    textlist.extend(text.split())
                    continue
                    #text, chunk = chunk.split('\r\n', 1)
                    #if chunk:
                        #chunklist.appendleft(chunk)
                        #text = str(updn_sep(text))
                        #textlist.extend(text.split())
                        #continue
                except IndexError:
                    break
            else:
                break

        if quoted:
            quoted.append(atom)
            if DQUOTE in atom:
                atom = ' '.join(quoted).strip(' "')
                quoted.clear()
                #result[-1].append(atom)
                cur_result.append(atom)
        elif DQUOTE in atom:
            quoted.append(atom)
        elif atom in DOWN:
            #assert not any(( x for x in UP if x in atom)), 'found DOWN and UP in same atom'
            #go_down(result)
            cur_result = deque()
            result[-1].append(cur_result)
            result.append(cur_result)
        elif atom in UP:
            #assert not any(( x for x in DOWN if x in atom)), 'found DOWN and UP in same atom'
            #go_up(result)
            result.pop()
            cur_result = result[-1]
        elif '{' in atom:
            bytes = int(atom.strip('{} '))
            chunk = chunklist.popleft()
            length = len(chunk)
            while length < bytes:
                chunk.extend(chunklist.popleft())
                length = len(chunk)
            cur_result.append(chunk)
            #chunk = chunklist.popleft()
            #data = chunk[:bytes]
            #del chunk[:bytes]
            #chunklist.appendleft(chunk)
            #cur_result.append(data)
        else:
            if atom.isdigit():
                atom = int(atom)
            elif atom == 'NIL':
                atom = None
            #result[-1].append(atom)
            cur_result.append(atom)

    return result


def scan_sexp():

    result, text, yield_structure = None, None, token_tree(None)
    quoted = deque()
    textlist= deque()
    
    while 1:
        result, text = ( yield yield_structure )
        cur_result = result[-1]
        if ( not isinstance(yield_structure, token_tree) or
                result is not yield_structure.results ):
            yield_structure = token_tree(result)

        text = updn_sep(text)
        textlist.extend(map(intern, text.split()))

        while 1:
            try: atom = textlist.popleft()
            except IndexError:
                if len(result) > 1:
                    yield_structure = need_more(result, 'readline', [])
                break

            if quoted:
                quoted.append(atom)
                if DQUOTE in atom:
                    atom = ' '.join(quoted).strip(' "')
                    quoted.clear()
                    cur_result.append(atom)

            elif DQUOTE in atom:
                quoted.append(atom)

            elif atom in DOWN:
                cur_result = result_container_type()
                result[-1].append(cur_result)
                result.append(cur_result)

            elif atom in UP:
                result.pop()
                cur_result = result[-1]

            elif '{' in atom:
                bytes = int(atom.strip('{} '))
                y = need_more(result, 'read', [bytes])
                atom = ( yield y )[1]
                cur_result.append(atom)
                del y

            else:
                if atom.isdigit():
                    atom = int(atom)
                elif atom is NIL:
                    atom = None
                cur_result.append(atom)


def lexer_loop(self):
    results = [[]]
    while 1:
        line = self.transport.readline()
        if not line: break
        while 1:
            parsed = self.parser.send((results, line))
            if isinstance(parsed, need_more):
                line = getattr(self.transport, parsed.transportmethod)(*parsed.args)
            else:
                self.parseque.appendleft(results)
                results = [[]]
                break


class mockcontainer(object):

    _do_work = lexer_loop

    def do_work(self):
        self.transport.seek(0)
        self.parseque.clear()
        self._do_work()

    def __init__(self, s):
        self.transport = StringIO(s)
        self.parseque = deque()
        self.parser = scan_sexp()
        self.parser.next()


if __name__ == '__main__':
    from time import time
    itx = 1000
    rit = xrange(itx)

    text = '266 FETCH (FLAGS (\Seen) UID 31608 INTERNALDATE "30-Jan-2008 02:48:01 +0000" RFC822.SIZE 4509 ENVELOPE ("Tue, 29 Jan 2008 14:00:24 +0000" "Aprenda as tXcnicas e os truques da cozinha mais doce..." (("Ediclube" NIL "ediclube" "sigmathis.info")) (("Ediclube" NIL "ediclube" "sigmathis.info")) ((NIL NIL "ediclube" "sigmathis.info")) ((NIL NIL "helder" "example.com")) NIL NIL NIL "<64360f85d83238281a27b921fd3e7eb3@localhost.localdomain>"))'
    text = '* 69 FETCH (UID 152132 FLAGS (\Seen) INTERNALDATE " 1-Feb-2010 17:14:13 -0700" RFC822.SIZE 994 BODY[HEADER.FIELDS (Message-ID)] {86}\r\nMessage-ID: <DC39B2A54BA9FF409E5BE5A51D4AE1FE0C6ED2DB@Exchange2k3.corp.stamps.com>\r\n\r\n)\r\n'
    text = '* 69 FETCH (INTERNALDATE " 1-Feb-2010 17:14:13 -0700" FLAGS (\Seen) UID 152132 BODY[HEADER.FIELDS (Message-ID)] {86}\r\nMessage-ID: <DC39B2A54BA9FF409E5BE5A51D4AE1FE0C6ED2DB@Exchange2k3.corp.stamps.com>\r\n\r\n RFC822.SIZE 994)\r\n'
    text = '* LIST (\Marked \HasNoChildren) "/" "Public Folders/Marketing/Archives/E-Commerce/Ecommerce Web Leads/Affiliates/Auction Sites/tradenswap"\r\n'
    text = '* 69 FETCH (INTERNALDATE " 1-Feb-2010 17:14:13 -0700" FLAGS (\Seen) UID 152132 BODY[HEADER.FIELDS.NOT (Message-ID)] {703}\r\nX-MimeOLE: Produced By Microsoft Exchange V6.5\r\nReceived: by Exchange2k3.corp.stamps.com\r\n.id <01CAA39C.A686F823@Exchange2k3.corp.stamps.com>; Mon, 1 Feb 2010 17:14:13 -0700\r\nMIME-Version: 1.0\r\nContent-Type: text/plain;\r\n.charset="us-ascii"\r\nContent-Transfer-Encoding: quoted-printable\r\nContent-class: urn:content-classes:message\r\nSubject: Feb 01, 2010 Generator Test\r\nDate: Mon, 1 Feb 2010 17:14:18 -0700\r\nX-MS-Has-Attach: \r\nX-MS-TNEF-Correlator: \r\nThread-Topic: Feb 01, 2010 Generator Test\r\nThread-Index: AcqjnKk8C1ctyOJ4QJabDqERnAg9Wg==\r\nFrom: "Benjamin Pak-To Siu" <bsiu@stamps.com>\r\nTo: "Data Center Operations" <DCO@Stamps.com>,\r\n."PCI" <PCI@stamps.com>,\r\n."Steve Spring" <Sspring@Stamps.com>\r\n\r\n RFC822.SIZE 994)\r\n'

    print 'Test to the s-exp parser:'
    print
    tobj = mockcontainer(text)

    print 'Non Recursive (%d times):' % itx
    a = time()
    for i in rit:
        tobj.do_work()
    b = time()
    print 1000 * (b-a) / itx, 'ms/iter'
    print itx, ' --> ', 1000 * (b-a) , 'ms'
    print
    print tobj.parseque
