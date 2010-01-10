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

'''Parse the fetch responses.
'''

# Imports
from utils import getUnicodeHeader, getUnicodeMailAddr, envelopedate2datetime
from sexp import scan_sexp

# Body structure

class BODYERROR(Exception) : pass

class BodyPart(object):
    def __init__( self, structure, prefix, level, next, parent = None ):
        self.parent = parent

    def query(self):
        raise BODYERROR('This part is not numbered')

    def load_parts( self, structure, prefix ):
        raise BODYERROR('This part is not numbered')

    def fetch_query(self):
        '''Fetch query to retrieve this part'''
        raise BODYERROR('This part is not numbered')

    def represent(self):
        '''Returns a string that depicts the message structure. Only for
        informational pourposes.
        '''
        raise BODYERROR('Abstract method')

    # Methods to facilitate displaying the message:

    def serial_message(self):
        '''Returns the message structure as a one dimension list'''
        return [self]

    def find_part(self, part_number ):
        '''Returns a part'''
        for part in self.serial_message():
            if part.part_number == part_number:
                return part
        raise BODYERROR('Didn\'t find the requested part (%s).' % part_number)

    def is_text(self):
        '''Only true for media='TEXT' media_subtype='PLAIN' or 'HTML' '''
        return False

    def is_basic(self):
        '''Only true for media!='TEXT' '''
        return False

    def is_multipart(self):
        '''Only true for media='MULTIPART'  '''
        return False

    def test_media(self, media ):
        return self.media == media.upper()

    def test_subtype(self, media_subtype):
        return self.media_subtype == media_subtype.upper()

    def test_plain(self):
        return self.test_subtype('PLAIN')

    def test_html(self):
        return self.test_subtype('HTML')

    def is_encapsulated(self):
        '''Only valid for encapsulated messages'''
        return False

    def is_attachment(self):
        '''Only valid for single parts that are attachments'''
        return self.is_basic()

class Multipart ( BodyPart ):
    def __init__( self, structure, prefix, level, next, parent = None  ):
        BodyPart.__init__( self, structure, prefix, level, next, parent )

        if next: # has part number
            self.part_number = '%s%d' % (prefix, level)
            prefix = '%s%d.' % ( prefix, level )
        else:
            next = True
            self.part_number = None

        self.media = 'MULTIPART'
        self.part_list = []
        self.body_ext_mpart = []
        self.load_parts(structure, prefix, level, next )

    def load_parts( self, structure, prefix, level, next ):
        is_subpart = True
        level = 1
        for part in structure:
            if is_subpart:
                if isinstance( part, list ):
                    # We have one more subpart
                    self.part_list.append( load_structure( part, prefix, level,
                        next, self))
                    level += 1
                else:
                    # The subpart list ended, the present field is the media
                    # subtype
                    is_subpart = False
                    self.media_subtype = part
            else:
                # We have body_ext_mpart, for now we ignore this
                self.body_ext_mpart.append( part )

    def __str__(self):
        return '<MULTIPART/%s>' % self.media_subtype

    def represent( self ):
        try:
            rpr = '%-10s %s/%s\n' % ( self.part_number, self.media,
                self.media_subtype )
        except:
            rpr = '%-10s %s/%s\n' % ( ' ', self.media, self.media_subtype )

        for part in self.part_list:
            rpr += part.represent()

        return rpr

    def fetch_query(self, media, media_subtype):
        tmp_query = []
        for part in self.part_list:
            query = part.fetch_query(media, media_subtype)
            if query:
                tmp_query.append(query)

        return ' '.join(tmp_query)

    def serial_message(self):
        tmp_partlist = [self]
        for part in self.part_list:
            tmp_partlist += part.serial_message()

        return tmp_partlist

    def is_multipart(self):
        '''Only true for media='MULTIPART'  '''
        return True

class Single ( BodyPart ):
    def __init__(self, structure, prefix, level, next, parent = None):
        BodyPart.__init__( self, structure, prefix, level, next, parent )
        self.media = structure[0].upper()
        self.media_subtype = structure[1].upper()
        self.body_fld_id = structure[3]
        self.body_fld_desc = structure[4]
        self.body_fld_enc = structure[5]
        self.body_fld_octets = structure[6]

        # body_fld_param = structure[2]
        # if body_fld_param is NIL, then there are no param
        self.body_fld_param = {}
        if structure[2]:
            it = iter(structure[2])
            for name,value in zip(it,it):
                if name:
                    self.body_fld_param[name] = value

        self.part_number = '%s%d' % (prefix, level)

    def charset(self):
        if self.body_fld_param.has_key('CHARSET'):
            return self.body_fld_param['CHARSET']
        else:
            return 'iso-8859-1'

    def filename(self):
        # TODO: first look for the name on the Content-Disposition header
        # and only after this one should look on the Contant-Type Name parameter
        if self.body_fld_param.has_key('NAME'):
            return getUnicodeHeader(self.body_fld_param['NAME'])
        else:
            return None

    def represent(self):
        return '%-10s %s/%s\n' % ( self.part_number, self.media,
            self.media_subtype )

    def __str__(self):
        return '<%s/%s>' % ( self.media, self.media_subtype )


class Message( Single ):
    def __init__( self, structure, prefix, level, next, parent = None ):
        Single.__init__(self, structure, prefix, level, next, parent )

        prefix = '%s%d.' % ( prefix, level )
        if isinstance( structure[8], list ):
            # Embeded message is a multipart
            next = False

        # Rest
        self.envelope = Envelope( structure[7] )
        self.body =  load_structure( structure[8], prefix, 1, next, self )
        self.body_fld_lines = structure[9]

        if len(structure)>10:
            self.body_ext_1part = structure[10:]

        self.start = True

    def represent(self):
        rpr = Single.represent(self)
        rpr += self.body.represent()
        return rpr

    def fetch_query(self, media, media_subtype):
        return self.body.fetch_query(media, media_subtype)

    def serial_message(self):
        return [self] + self.body.serial_message() + [self]

    def is_encapsulated(self):
        return True

    def is_start(self):
        tmp = self.start
        self.start = not self.start
        return tmp

class SingleTextBasic ( Single ):
    def __init__( self, structure, prefix, level, next, parent = None ):
        Single.__init__( self, structure, prefix, level, next, parent )

    def __str__(self):
        return '<%s/%s>' % ( self.media, self.media_subtype )

    def query(self):
        return 'BODY[%s]' % self.part_number

    def fetch_query(self, media, media_subtype):
        if (self.media == media and self.media_subtype == media_subtype) or \
           (self.media == media and media_subtype== '*') or \
           (media == '*' and self.media_subtype == media_subtype) or \
           (media == '*' and media_subtype == '*'):
            return self.query()
        else:
            return None

class SingleText ( SingleTextBasic ):
    def __init__(self, structure, prefix, level, next, parent = None):
        SingleTextBasic.__init__(self, structure, prefix, level, next, parent )
        self.body_fld_lines = structure[7]

        if len(structure)>8:
            self.body_ext_1part = structure[8:]
        else:
            self.body_ext_1part = None

    def is_text(self):
        return True

class SingleBasic ( SingleTextBasic ):
    def __init__(self, structure, prefix, level, next, parent = None):
        SingleTextBasic.__init__(self, structure, prefix, level, next, parent )

        if len(structure)>7:
            self.body_ext_1part = structure[7:]
        else:
            self.body_ext_1part = None

    def is_basic(self):
        '''Only true for media!='TEXT' '''
        return True

def load_structure(structure, prefix = '',level = 1,next = False,parent = None):
    if isinstance( structure[0], list ):
        # It's a multipart
        return Multipart(structure, prefix, level, next, parent)

    media = structure[0].upper()
    media_subtype = structure[1].upper()

    if media == 'MESSAGE' and media_subtype == 'RFC822':
        return Message( structure, prefix, level, next, parent )

    if media == 'TEXT':
        return SingleText( structure, prefix, level, next, parent )

    return SingleBasic( structure, prefix, level, next, parent )

def envelope( structure ):
    return { 'env_date': envelopedate2datetime(structure[0]),
            'env_subject': getUnicodeHeader(structure[1]),
            'env_from': getUnicodeMailAddr(structure[2]),
            'env_sender': getUnicodeMailAddr(structure[3]),
            'env_reply_to': getUnicodeMailAddr(structure[4]),
            'env_to': getUnicodeMailAddr(structure[5]),
            'env_cc': getUnicodeMailAddr(structure[6]),
            'env_bcc': getUnicodeMailAddr(structure[7]),
            'env_in_reply_to': structure[8],
            'env_message_id': structure[9]  }

def real_name( address ):
    '''From an address returns the person real name or if this is empty the
    email address'''
    if address[0]:
        return address[0]
    else:
        return address[1]

class Envelope( dict ):
    def __init__( self, env ):
        dict.__init__(self, envelope( env ) )

    def short_mail_list(self, mail_list):
        for addr in mail_list:
            yield real_name(addr)

    def to_short(self):
        '''Returns a list with the first and last names'''
        return self.short_mail_list(self['env_to'])

    def from_short(self):
        '''Returns a list with the first and last names'''
        return self.short_mail_list(self['env_from'])

class FetchParser( dict ):
    '''This class parses the fetch response (already as a python dict) and
    further processes.
    '''

    def __init__(self, result):
        # Scan the message and make it a dict
        it = iter(scan_sexp(result)[0])
        result = dict(zip(it,it))

        dict.__init__(self, result )

        for data_item in self:
            method_name = data_item + '_data_item'
            meth = getattr(self, method_name, self.default_data_item )
            self[data_item] = meth( self[data_item] )

    def default_data_item(self, data_item):
        return data_item

    def BODY_data_item(self, body ):
        return load_structure(body)

    BODYSTRUCTURE_data_item = BODY_data_item

    def ENVELOPE_data_item(self, envelope ):
        return Envelope(envelope)

if __name__ == '__main__':
    from imaplib2.imapp import IMAP4P

    import getopt, getpass, sys, pprint

    try:
        optlist, args = getopt.getopt(sys.argv[1:], 'd:s:')
    except getopt.error, val:
        optlist, args = (), ()

    if not args: args = ('',)

    host = args[0]

    USER = getpass.getuser()
    PASSWD = getpass.getpass("IMAP password for %s on %s: " % (USER, host or "localhost"))

    M = IMAP4P( host )

    M.login(USER,PASSWD)

    M.select('INBOX')
    msg_list = M.search_uid('(ALL)')

    msg_list = [31911]

    bodies = M.fetch_uid( msg_list, '(BODYSTRUCTURE)' )
    M.logout()

    for uid in msg_list:
        print '\n'*2
        print 'UID:', uid
        pprint.pprint(bodies[uid])
        print
        for part in walk(bodies[uid]['BODYSTRUCTURE']):
            if part.has_key('part_number'):
                print '%-10s %s/%s' % ( part['part_number'], part['media'],
                    part['media_subtype'] )
            else:
                print '%10s %s/%s' % (' ', part['media'],
                    part['media_subtype'] )


################################################################################
# The following funtions were used to understand the body structure structure  #
# and to see how the numbering algorithm for the messages works. They're kept  #
# here for historical and reference resons.                                    #
################################################################################

def body_parts( structure ):
    '''This function analyses a s-exp body structure as returned by the server
    and creates a python structure.

    @param structure: a BODY or BODYSTRUCTURE fetch response formated as a
    python list (as resturnd by L{scan_sexp<imaplib2.sexp.scan_sexp>}).
    @type structure: list

    @return: a dict with the parsed structure.
    '''

    if isinstance(structure[0], list):
        # It's a multipart

        multipart = { 'media': 'MULTIPART', 'part_list': [] }
        is_subpart = True
        for part in structure:
            if is_subpart:
                if isinstance(part, list):
                    # We have one more subpart
                    multipart['part_list'].append( body_parts( part ) )
                else:
                    # The subpart list ended, the present field is the
                    # media_subtype
                    is_subpart = False
                    multipart['media_subtype'] = part
            else:
                # We have body_ext_mpart, for now we ignore this
                if multipart.has_key('body_ext_mpart'):
                    multipart['body_ext_mpart'].append(part)
                else:
                    multipart['body_ext_mpart'] = []
                    multipart['body_ext_mpart'].append(part)

        return multipart

    # We are parsing a message part
    part = { 'media': structure[0],
             'media_subtype': structure[1],
             'body_fld_id': structure[3],
             'body_fld_desc': structure[4],
             'body_fld_enc': structure[5],
             'body_fld_octets': structure[6] }

    # body_fld_param = structure[2]
    # if body_fld_param is NIL, then there are no param
    if structure[2]:
        it = iter(structure[2])
        for name,value in zip(it,it):
            if name:
                part[name] = value

    as_ext = False

    if structure[0] == 'TEXT':
        # body type text
        part['body_fld_lines'] = structure[7]
        if len(structure) > 8:
            structure = structure[8:]
            as_ext = True

    elif structure[0] == 'MESSAGE' and \
         structure[1] == 'RFC822':
        # body type message
        part['envelope'] = Envelope( structure[7] )
        part['body'] = body_parts( structure[8] )
        part['body_fld_lines'] = structure[9]
        if len(structure) > 10:
            structure = structure[10:]
            as_ext = True

    else:
        if len(structure) > 7:
            structure = structure[7:]
            as_ext = True

    if as_ext:
        # has a body_ext_1part, we ignore this for the moment
        part['body_ext_1part'] = structure

    return part

def calc_part_numbers( body, prefix = '', level = 1, next = False ):
    if body['media'] == 'MULTIPART':
        if next: # has part number
            body['part_number'] = '%s%d' % (prefix, level)
            prefix = '%s%d.' % ( prefix, level )
        else:
            next = True

        for part in body['part_list']:
            calc_part_numbers(part, prefix, level, next)
            level += 1
    else:
        body['part_number'] = '%s%d' % (prefix, level)
        if body['media'] == 'MESSAGE' and body['media_subtype'] == 'RFC822':
            prefix = '%s%d.' % ( prefix, level )
            if body['body']['media'] == 'MULTIPART':
                next = False
            calc_part_numbers(body['body'], prefix, 1, next)

    return body

def walk( body ):
    '''Iteracts through the message parts
    '''
    if body['media'] == 'MULTIPART':
        yield body
        for part in body['part_list']:
            for p in walk(part):
                yield p

    else:
        if body['media'] == 'MESSAGE' and body['media_subtype'] == 'RFC822':
            yield body
            for p in walk( body['body'] ):
                yield p
        else:
            yield body

def represent_body( structure ):
    print 'Recursive'
    body = calc_part_numbers( body_parts ( structure ) )
    for part in walk(body):
        if part.has_key('part_number'):
            print '%-10s %s/%s' % ( part['part_number'], part['media'],
                part['media_subtype'] )
        else:
            print '%-10s %s/%s' % ( 'None', part['media'],
                part['media_subtype'] )
