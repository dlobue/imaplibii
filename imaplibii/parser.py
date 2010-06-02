import cgitb
cgitb.enable(format='text')

from collections import deque, namedtuple
from cStringIO import StringIO
from functools import partial
from itertools import islice

from utils import Blank, memoize, Internaldate2tuple

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
                t = need_more(result, 'read', [bytes])
                atom = ( yield t )[1]
                if hasattr(cur_result[-1], '__iter__'):
                    atom = [ cur_result.pop(), atom ]
                cur_result.append(atom)
                del t

            else:
                if atom.isdigit():
                    atom = int(atom)
                elif atom is NIL:
                    atom = None
                cur_result.append(atom)


# Response tag type containers
untagged = namedtuple('untagged', 'tag type data')
continuation = namedtuple('continuation', 'tag data')
tagged = namedtuple('tagged', 'tag type data')

response_typemap = {
                  '*': untagged,
                  '+': continuation,
                }
def get_resp_container(tag):
    return response_typemap.get(tag, tagged)

# Response data containers for different response types (fetch, status, list, etc)
notice = namedtuple('notice', 'id')
list_item = namedtuple('list_item', 'attribs delim name')
info = namedtuple('information', 'data human_readable')

@memoize
def response_container_factory(cmd, *args, **kwargs):
    def fmtprep(key,detail):
        if detail is not Blank and '.' in key:
            key = key.split('.')[0]
        elif '.' in key:
            key = key.replace('.','')
        return key
    k = ' '.join((fmtprep(k,d) for k,d in kwargs.iteritems()))
    a = ' '.join((x for x in args))
    s = '%s %s' % (a,k)
    r = namedtuple(cmd, s.lower())
    return r


response_datamap = {
    'fetch': partial(response_container_factory, 'fetch', 'id'),
    'status': partial(response_container_factory, 'status', 'name'),
    'list': list_item,
    'lsub': list_item,
    'ok': info,
    'no': info,
    'bad': info,
    'bye': info,
                }

def get_resp_data_container(rtype):
    return response_datamap.get(rtype, list)

modval_map = {
    'INTERNALDATE': Internaldate2tuple,
    }


def postparse(sexp):
    data = None
    isexp = iter(sexp)
    tag = isexp.next()
    tcontainer = get_resp_container(tag)
    if tcontainer is continuation:
        data = ' '.join(map(str, isexp))
        return tcontainer(tag, data)
    rtype = isexp.next()
    if isinstance(rtype, int):
        #not the rtype, just an imposter
        data = rtype
        rtype = isexp.next()
    rtype = rtype.lower()

    if len(sexp) is 3 and data:
        #it is a notice response. ex: * 1 exists
        r = tcontainer(tag, rtype, data=notice(data))
    else:
        dcontainer = get_resp_data_container(rtype)
        if dcontainer is list_item:
            assert not data, 'Somehow there already is data inside temp data container'
            r = tcontainer(tag, rtype, data=dcontainer(*isexp))
        elif dcontainer is info:
            assert not data, 'Somehow there already is data inside temp data container'
            data = [isexp.next()]
            if not hasattr(data[0], '__iter__'):
                readable = data.extend(isexp)
                data = None
            else: readable = (x for x in isexp)
            try: readable = ' '.join(readable)
            except TypeError: pass
            r = tcontainer(tag, rtype, data=dcontainer(data=data, human_readable=readable))
        elif dcontainer is list:
            r = tcontainer(tag, rtype, data=dcontainer(isexp))
        else:
            if data is None:
                data = isexp.next()
            imapmap = isexp.next()
            try:
                t = isexp.next()
                t = ' '.join(map(str, sum([t], isexp)))
                s = 'The sexp iterable should be empty, but still has values left?\nleft: %r\ntag: %s\nrtype: %s\n%r' % (t, tag, rtype, dcontainer)
                raise ValueError(s)
            except StopIteration: pass

            keys = (x.replace('.','') for x in islice(imapmap, 0, None, 2))
            dcontainer = dcontainer(*keys)

            def imodvalues(imapmap):
                s, c = 2, 0
                while 1:
                    try: field, value = imapmap[s*c:s*(c+1)]
                    except ValueError:
                        break
                    c+=1
                    func = modval_map.get(field, lambda x: x)
                    yield func(value)
                
            #values = islice(imapmap, 1, None, 2)
            values = imodvalues(imapmap)
            r = tcontainer(tag, rtype, data=dcontainer(data, *values))

    return r


def _build_ok_response_container(*args):
    iargs = iter(args)
    if hasattr(args[0], '__iter__'):
        data = iargs.next()
    else: data = None
    r = info(data=data, human_readable=' '.join(iargs))
    return r

_build_no_response_container = _build_ok_response_container
_build_bad_response_container = _build_ok_response_container
_build_bye_response_container = _build_ok_response_container



def lexer_loop(self, container=False, earlyexit=False):
    while 1:
        results = [[]]
        line = self.transport.readline()
        if not line:
            if earlyexit: break
            continue
        while 1:
            parsed = self.preparse.send((results, line))
            if isinstance(parsed, need_more):
                line = getattr(self.transport, parsed.transportmethod)(*parsed.args)
            else:
                r = self.postparse(results[0])
                if container is False:
                    yield r
                else: container.append(r)
                break


class mockcontainer(object):

    _do_work = lexer_loop

    def do_work(self):
        self.transport.seek(0)
        self.parseque.clear()
        self._do_work(container=self.parseque, earlyexit=True)

    def __init__(self, s, transport=StringIO, postparse=postparse):
        self.transport = transport(s)
        self.parseque = deque()
        self.preparse = scan_sexp()
        self.preparse.next()
        self.postparse = staticmethod(postparse)


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
    #tobj = mockcontainer('imapsession-1275238402.04.log', partial(open, mode='r'))

    print 'Non Recursive (%d times):' % itx
    a = time()
    for i in rit:
        tobj.do_work()
    b = time()
    print 1000 * (b-a) / itx, 'ms/iter'
    print itx, ' --> ', 1000 * (b-a) , 'ms'
    print
    #print tobj.parseque

