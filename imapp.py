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
# $LastChangedDate: 2008-04-28 12:49:27 +0100 (Mon, 28 Apr 2008) $
# $LastChangedRevision: 332 $
# $LastChangedBy: helder $
# 

'''This is an IMAP parsed library. The final objective is to have a
library which iteracts with an IMAP server (just like imaplib) and parses to 
python structures all the server responses.

Since the server will respond with multiple untagged responses to a given 
command, each untagged response will update the <instance>.sstatus with the
appropriate data which will be return at the command end.
'''

# Global imports
import re

# Local imports
from imapll import IMAP4, IMAP4_SSL
from infolog import InfoLog
from imapcommands import COMMANDS, STATUS
from utils import makeTagged, unquote, Internaldate2tuple, shrink_fetch_list
from parsefetch import FetchParser
from parselist import ListParser
from sexp import scan_sexp

# Constants
D_NOTPARSED = 8
Debug = D_NOTPARSED
IMAP4_PORT = 143
IMAP4_SSL_PORT = 993
MAXLOG = 100
CRLF = '\r\n'
SP = ' '

# Regexp
opt_respcode_re = re.compile(r'^\[(?P<code>[a-zA-Z0-9-]+)(?P<args>.*?)\].*$')
response_re = re.compile(r'^(?P<code>[a-zA-Z0-9-]+)(?P<args>.*)$', re.MULTILINE)
fetch_msgnum_re = re.compile(r'^(\d+) ')
fetch_data_items_re = re.compile(r'^([a-zA-Z0-9\[\]<>\.]+) ')
fetch_flags_re = re.compile(r'^\((.*?)\) ?')
fetch_int_re = re.compile(r'^(\d+) ?')
fetch_quoted_re = re.compile(r'^"(.*?)" ?')
map_crlf_re = re.compile(r'\r\n|\r|\n')
mailbox_list_re = re.compile( r'\((?P<attributes>.*?)\)' + SP + \
                              r'(?P<hierarchy_delimiter>"."|NIL)' + SP + \
                              r'"(?P<name>.*?)"' )


class IMAP4P:
    '''
    This class implements an IMAP client.
    
    The state of the client is stored in <instance>.sstatus, this is a 
    dictionary. 
    
    For instance, when we select a mailbox on the server, the related responses
    are stored in <instance>.sstatus['current_folder']. If we close this mailbox 
    <instance>.sstatus['current_folder'] reverts to {}.

    Besides putting the server responses on this structure, other usefull 
    information is also stored there. For instance, under 'current_folder' we 
    also put the folder name whish is not present on the server responses.
    
    A log of the client activity is also kept in <instance>.infolog, this is 
    an instance of InfoLog, this can be redifined to suit our needs. InfoLog
    implements a simple callback mechanism. We can add specific actions to 
    be performed when a certain type of log is made.
    
    The IMAP commands implemented on this class follow RFC3501 unless otherwise
    noted.
    
    TODO: Think about transforming the IMAP4P.sstatus so that we can also define
    callbacks when certain values change on this structure.
    
    The <instance>.sstatus dict as the following empty state::
    
                      { 'current_folder': {},
                        'capability' : (),
                        'sort_response': {},
                        'list_response': { 'mailbox_list': [], 
                                           'hierarchy_delimiter': '' },
                        'search_response': (),
                        'sort_response': (),
                        'status_response': {},
                        'fetch_response': {},                       
                        'acl_response': { 'mailbox': '',
                                          'acl': {} },
                                         
                         'listrights_response': { 'mailbox': '',
                                                  'identifier': '',
                                                  'req_rights': '',
                                                  'opt_rights': () },
                         'myrights_response':   { 'mailbox': '',
                                                 'rights': '' },
                         'namespace': '',
                       }
                       
        Please note the when the object is destroied we do an automatic logout,
        you can still use the logout method, but in that case you should 
        override the __del__ method, else your're going to raise an exception
        when you try to logout from a closed connection when the object is 
        deleted.
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
    
    def __init__(self, 
            host, 
            port=None,
            ssl = False,
            keyfile = None, 
            certfile = None, 
            infolog = InfoLog(MAXLOG),
            autologout = True ):
                
        # Choose the right connection, and then connect to the server
        if not port:
            if ssl:
                port = IMAP4_SSL_PORT
            else:
                port = IMAP4_PORT
        
        if ssl:
            self.__IMAP4 = IMAP4_SSL( host = host, port = port, 
                keyfile = keyfile, certfile = certfile,
                parse_command = self.parse_command )
        else:
            self.__IMAP4 = IMAP4( host = host, port = port, 
                parse_command = self.parse_command )
        
        # Wrap IMAP4
        self.welcome = self.__IMAP4.welcome
        self.send_command = self.__IMAP4.send_command
        self.state = self.__IMAP4.state
        
        # Server status
        self.sstatus = {}

        # Status messages from the server
        self.infolog = infolog
        self.infolog.addEntry('WELCOME', self.welcome)
        
        self.capabilities = []
        self.as_uid = None
        self.as_sort = None
        
        self.autologout = autologout
        
    def __del__(self):
        if self.autologout:
            self.logout()
            self.shutdown()

    ##
    # Response parsing
    ##
    
    def _parse_tagged(self, tag, tagged_responses):
        '''Tagged response handling'''

        for tag in tagged_responses:
            tagged = tagged_responses[tag]
            status = tagged['status'].upper()
            if status in ('OK','NO','BAD'):
                if status == 'OK':
                    # Information, update the server info log
                    self.infolog.addEntry('OK', tagged )
                elif status == 'NO':
                    # Server operational error, the command failed
                    self.infolog.addEntry('NO', tagged )
                elif status == 'BAD':
                    self.infolog.addEntry('BAD', tagged )
                    raise self.Error('Protocol-level error, check the '  
                        'command syntaxe. \n%s' % (makeTagged(tagged)))
            else:
                raise self.Error('Bad response status from '
                    'the server. \n%s' % (makeTagged(tagged)))
                    
            # Check if there are optional response codes:
            self.parse_optional_codes(tagged['message'])
    
    def _parse_untagged(self, tag, untagged_response):
        '''Untagged response handling'''
        
        for untagged in untagged_response:
            untagged = untagged[2:]
            # get the response type
            resp = response_re.match(untagged)
            if not resp:
                raise self.Error('Parse error: %s' % untagged)
            else:
                code = resp.group('code').upper()
                args = untagged[resp.start('args'):].strip()
                
                # Some responses come with an integer at the begining
                # if that's the case, we switch the order of this response
                try:
                    int(code)
                    resp2 = response_re.match(args)
                    code, args = resp2.group('code').upper(), \
                                 (code + args[resp2.start('args'):]).strip()
                except:
                    pass
                
                # Call handler function based on the response type
                method_name = code.replace('.', '_')+'_response'
                meth = getattr(self, method_name, self.default_response)
                meth( code, args )
                
    def parse_command(self, tag, response):
        '''Further processing of the server response.
        '''
        self._parse_tagged(tag, response['tagged'])
        self._parse_untagged(tag, response['untagged'])  
        
        return response
     
    def default_response(self, code, args):
        if __debug__:
            if Debug & D_NOTPARSED:
                print 'Don\'t know how to handle:\n * %s %s' % (code, args)
        
    def parse_optional_codes(self, message):
        opt_respcode = opt_respcode_re.match(message)
        if opt_respcode:
            code = opt_respcode.group('code').upper()
            args = opt_respcode.group('args').strip()
            
            if code not in STATUS: 
                if __debug__:
                    if Debug & D_NOTPARSED:
                        print 'Don\'t know how to handle optional code:\n%s'% \
                            message
                return # Silently ignore unknown OPTIONAL codes

            # Integer responses:    
            try:
                self.sstatus['current_folder'][code.upper()] = int(args)
                return
            except:
                pass
            
            # Parenthesised list
            try:
                if args[0] == '(' and args[-1] == ')':
                    args = tuple( args[1:-1].split() )
                    self.sstatus['current_folder'][code.upper()] = args
                    return
            except:
                pass
             
            # Atoms
            if code == 'READ-ONLY':
                self.sstatus['current_folder']['is_readonly'] = True
            elif code == 'READ-WRITE':
                self.sstatus['current_folder']['is_readonly'] = False
            elif code in ('ALERT', 'TRYCREATE', 'PARSE'):
                self.infolog.addEntry(code, message )
            else:
                raise self.Error('Don\'t know how to parse  %s - %s' % \
                    (code, args))
    
    def ACL_response(self, code, args):
        response = scan_sexp(args)

        it = iter(response[1:])
        acl = dict(zip(it,it))

        self.sstatus['acl_response'] = { 'mailbox': response[0],
                                        'acl': acl }

    def BYE_response(self, code, args):
        self.parse_optional_codes(args)
        self.infolog.addEntry(code, args )

    def CAPABILITY_response(self, code, args):
        self.sstatus['capability'] = tuple( args.upper().split() )
        
    def EXISTS_response(self, code, args):
        self.sstatus['current_folder']['EXISTS'] = int(args)
        
    def EXPUNGE_response(self, code, args):
        self.sstatus['current_folder']['expunge_list'].append(int(args))
        
    def FETCH_response(self, code, args):
        # Message number
        fresp = fetch_msgnum_re.match(args)
        
        if not fresp:
            raise self.Error('Problem parsing the fetch response.')
        
        msg_num = int(fresp.groups()[0])
        
        # Parse the response:
        self.sstatus['fetch_response'][msg_num]=FetchParser(args[fresp.end():])
        
    def FLAGS_response(self, code, args):
        args = tuple( args[1:-1].split() )
        self.sstatus['current_folder'][code.upper()] =  args 
        
    def LIST_response(self, code, args):
        resp = mailbox_list_re.match(args)
        
        if not resp:
            raise self.Error('Don\'t know how to parse the LIST response: %s' %\
                args )
        
        attributes =  tuple(resp.group('attributes').split())
        hierarchy_delimiter = resp.group('hierarchy_delimiter')
        name = resp.group('name')
        
        # If the hierarchy_delimiter is NIL no hierarchy exists
        if hierarchy_delimiter != 'NIL':
            hierarchy_delimiter = unquote(hierarchy_delimiter)
            name = tuple(name.split(hierarchy_delimiter))
        else:
            hierarchy_delimiter = None
        
        self.sstatus['list_response'].set_delimiter( hierarchy_delimiter )
        self.sstatus['list_response'].add_folder( name, attributes )
        
    LSUB_response = LIST_response
    
    def LISTRIGHTS_response(self, code, args):
        
        response = scan_sexp( args )
        
        self.sstatus['listrights_response'] = { 
            'mailbox': response[0],
            'identifier': response[1],
            'req_rights': response[2],
            'opt_rights': tuple(response[3]) }
    
    def MYRIGHTS_response(self, code, args):
        response = scan_sexp( args )
        
        self.sstatus['myrights_response'] = { 
            'mailbox': response[0],
            'rights': response[1] }
        
    def NAMESPACE_response(self, code, args):
        response = scan_sexp( args )
        self.sstatus['namespace'] = response
        
    def OK_response(self, code, args):
        self.parse_optional_codes(args)
       
    def RECENT_response(self, code, args):
        self.sstatus['current_folder']['RECENT'] = int(args)
      
    def SEARCH_response(self, code, args):
        self.sstatus['search_response'] = tuple([ int(Xi) for Xi in args.split()])
      
    def SORT_response(self, code, args):
        self.sstatus['sort_response'] = tuple([ int(Xi) for Xi in args.split() ])
        
    def STATUS_response(self, code, args):
        response = scan_sexp(args)
        it = iter(response[1])
        
        self.sstatus['status_response'] = dict(zip(it, it)) 
        self.sstatus['status_response']['mailbox'] = response[0] 

    ##
    # Command processing
    ##
    
    def _test_command(self, name):
        if self.state not in COMMANDS[name]:
            raise self.Error(
            'command %s illegal in state %s' % (name, self.state))
            
    def _checkok(self, tag, response):
        return response['tagged'][tag]['status'] == 'OK'
    
    def processCommand(self, name, args = None ):
        '''Processes the current comand.
        
        @param name: Valid IMAP4 command.
        @type  name: string
        
        @param args: Command arguments.
        @type  args: string
        
        @return: <instance>.sstatus
        '''
        # Verifies if it's a valid command
        self._test_command(name)
        
        # Composes the command
        if args:
            command = '%s %s' % ( name, args )
        else:
            command = name

        # Sends the command to the server, and parses the response
        tag, response = self.send_command(command)
        
        # Checks if the command was successfull
        if self._checkok(tag, response):
            return self.sstatus
        else:
            raise self.Error('Error in command %s - %s' % (name,
                response['tagged'][tag]['message']))
    
    ##
    # IMAP Commands
    ##
        
    def append(self, mailbox, message, flags=None, date_time=None):
        '''
        '''
        
        name = 'APPEND'
        
        message = map_crlf_re.sub('\r\n', message)
        message = '{%d}%s%s' % (len(message), CRLF, message )
            
        aux_args = []
        
        if flags:
            aux_args.append(flags)
            
        if date_time:
            aux_args.append(date_time)
            
        aux_args = ' '.join(aux_args)
        
        if aux_args:
            args = '"%s" %s %s' % (mailbox, aux_args, message)
        else:
            args = '"%s" %s' % (mailbox, message)
        
        return self.processCommand( name, args )
        
    def authenticate(self, mech, authobject ):
        '''
        Send an AUTHENTICATE command to the server.
        
        From the RFC:
        
        The AUTHENTICATE command indicates a [SASL] authentication
        mechanism to the server.  If the server supports the requested
        authentication mechanism, it performs an authentication protocol
        exchange to authenticate and identify the client.  It MAY also
        negotiate an OPTIONAL security layer for subsequent protocol
        interactions.  If the requested authentication mechanism is not
        supported, the server SHOULD reject the AUTHENTICATE command by
        sending a tagged NO response.
        
        @param mech: Authentication mechanism
        @type  mech: string
        @param authobject: Authentication object, or list of autentication
                           objects
        @type  authobject: callable, or string
        '''
        
        name = 'AUTHENTICATE'
        
        try:
            for obj in authobject:
                self.push_continuation( obj )
        except:
            self.push_continuation(authobject)
        
        return self.processCommand( name, mech )
        
    def capability(self):
        '''Fetch capabilities list from server.
        updates self.sstatus['capability']'''

        name = 'CAPABILITY'
        
        self.sstatus['capability'] = ''
        
        return self.processCommand( name )['capability']
        
    def check(self):
        '''Requests a checkpoint of the currently selected mailbox'''

        name = 'CHECK'
        
        return self.processCommand( name )
        
    def close(self):
        '''Close currently selected mailbox.

        Deleted messages are removed from writable mailbox.
        This is the recommended command before 'LOGOUT'.'''
        
        name = 'CLOSE'
    
        try:
            self.processCommand( name )
        finally:
            self.state = 'AUTH'
            
        return self.sstatus
        
    def copy(self, message_list, mailbox ):
        '''Copy messages to mailbox'''
        
        name = 'COPY'
        
        message_list = ','.join( '%s' % Xi for Xi in message_list)
        args = ' %s "%s"' % (message_list, mailbox)
        
        return self.processCommand( name, args )
        
    def create(self, mailbox):
        '''Create new mailbox.'''
        
        name = 'CREATE'
        
        return self.processCommand( name, '"%s"' % mailbox )
        
    def delete(self, mailbox):
        '''Delete a mailbox.'''
        
        name = 'DELETE'
        
        return self.processCommand( name, '"%s"' % mailbox )
        
    def deleteacl(self, mailbox, identifier):
        '''The DELETEACL command removes any <identifier,rights> pair for the
        specified identifier from the access control list for the specified
        mailbox.
        
        The server must support the ACL capability (RFC4314)
        
        http://www.ietf.org/rfc/rfc4314.txt
        '''
        name = 'DELETEACL'
        
        return self.processCommand( name, '"%s" %s' % (mailbox, identifier))
        
    def expunge(self):
        '''Permanently remove deleted items from selected mailbox.

        Generates 'EXPUNGE' response for each deleted message.
        '''
        
        name = 'EXPUNGE'
        
        self.sstatus['current_folder']['expunge_list'] = []
        
        return self.processCommand( name )['current_folder']['expunge_list']
        
    def fetch(self, message_list, message_parts='(FLAGS)' ):
        '''Fetch (parts of) messages.'''

        name = 'FETCH'
        
        self.sstatus['fetch_response'] = {}
        
        if isinstance(message_list, list) or \
           isinstance(message_list, tuple):
            message_list = shrink_fetch_list( message_list )
            message_list = ','.join( '%s' % Xi for Xi in message_list)

        return self.processCommand( name, '%s %s' % (message_list, 
            message_parts))['fetch_response']
        
    def getacl(self, mailbox):
        '''Get the ACLs for a mailbox.
        
        The server must support the ACL capability (RFC4314)
        
        http://www.ietf.org/rfc/rfc4314.txt
        '''
        
        name = 'GETACL'
        
        self.sstatus['acl_response'] = { 'mailbox': mailbox,
                                        'acl': {} }
        
        return self.processCommand( name, '"%s"' % mailbox )['acl_response']
        
    def list(self, directory='', pattern='*'):
        '''List mailbox names in directory matching pattern.
        '''
        
        name = 'LIST'
        
        self.sstatus['list_response'] = ListParser()
        
        return self.processCommand( name, '"%s" "%s"' % ( directory, 
            pattern ))['list_response']
        
    def listrights(self, mailbox, identifier):
        '''LISTRIGHTS command takes a mailbox name and an identifier and
        returns information about what rights can be granted to the
        identifier in the ACL for the mailbox.
        
        The server must support the ACL capability (RFC4314)
        
        http://www.ietf.org/rfc/rfc4314.txt
        '''
        
        name = 'LISTRIGHTS'
        
        self.sstatus['listrights_response'] = { 'mailbox': '',
                                               'identifier': '',
                                               'req_rights': '',
                                               'opt_rights': () }
                                        
        return self.processCommand( name, '"%s" %s' % (mailbox, 
            identifier))['listrights_response']
        
    def login(self, user, password):
        """Identify client using plaintext password.

        NB: 'password' will be quoted.
        """
        name = 'LOGIN'
        
        try:
            self.processCommand( name, '%s \"%s\"' % (user, password))
            self.state = 'AUTH'
        except:
            raise self.Error('Could not login.')
            
        return self.sstatus
        
    def login_cram_md5(self, user, password):
        """ Force use of CRAM-MD5 authentication.
        """
        self.user, self.password = user, password
        return self.authenticate('CRAM-MD5', self._CRAM_MD5_AUTH)
        
    def logout(self):
        '''
        '''
        name = 'LOGOUT'
        return self.processCommand( name )
        
    def _CRAM_MD5_AUTH(self, challenge):
        """ Authobject to use with CRAM-MD5 authentication. """
        import hmac
        response = self.user + " " + hmac.HMAC(self.password, challenge).hexdigest()
        
        del self.user
        del self.password
        return response
        
    def lsub(self, directory='', pattern='*'):
        '''List subscribed mailbox names in directory matching pattern.
        '''
        
        name = 'LSUB'
        
        self.sstatus['list_response'] = ListParser()
        
        return self.processCommand( name, '"%s" "%s"' % ( directory, 
            pattern ))['list_response']
      
    def myrights(self, mailbox):
        '''The MYRIGHTS command returns the set of rights that the user has to
        mailbox.
        
        The server must support the ACL capability (RFC4314)
        
        http://www.ietf.org/rfc/rfc4314.txt
        '''
        name = 'MYRIGHTS'
        
        self.sstatus['myrights_response'] = { 'mailbox': '',
                                             'rights': '' }
        
        return self.processCommand( name, 
            '"%s"' % (mailbox))['myrights_response']
        
    def namespace(self):
        '''
        '''
        name = 'NAMESPACE'
        self.sstatus['namespace'] = ''
        
        return self.processCommand( name )['namespace']
        
    def noop(self):
        '''NOOP the server'''
        name = 'NOOP'
        
        return self.processCommand( name )
        
    def rename(self, oldmailbox, newmailbox):
        '''
        '''
        name = 'RENAME'
        
        return self.processCommand( name, '"%s" "%s"' % (oldmailbox, 
            newmailbox))
        
    def search(self, criteria, charset=None):
        '''Search mailbox for matching messages'''
        name = 'SEARCH'
        self.sstatus['search_response'] = ()
        if charset:
            args = 'CHARSET %s %s' % ( charset, criteria)
        else:
            args = '%s' % criteria
        
        return self.processCommand( name, args)['search_response']
    
    def select(self, folder,readonly=False ):
        '''Selects a folder
        '''
        if readonly:
            name = 'EXAMINE'
        else:
            name = 'SELECT'
        
        self.sstatus['current_folder'] = {}
    
        self.processCommand( name, '"%s"' % folder)

        self.sstatus['current_folder']['name'] = folder
        self.state = 'SELECTED'
        
        return self.sstatus['current_folder']
        
    def setacl(self, mailbox, identifier, acl):
        '''The SETACL command changes the access control list on the specified
        mailbox so that the specified identifier is granted permissions as
        specified in the third argument
        
        The server must support the ACL capability (RFC4314)
        
        http://www.ietf.org/rfc/rfc4314.txt
        '''
        name = 'SETACL'
        
        return self.processCommand( name, '"%s" %s %s' % (mailbox, identifier, 
            acl))
        
    def sort(self, program, charset, search_criteria):
        '''The SORT command is a variant of SEARCH with sorting semantics for
        the results.
         
        The server must support the SORT capability 
         
        http://tools.ietf.org/html/draft-ietf-imapext-sort-19
        '''
         
        name = 'SORT'
         
        self.sstatus['sort_response'] = ()
        
        return self.processCommand( name, '%s %s %s' % (program, charset, 
            search_criteria))['sort_response']
        
    def status(self, mailbox, names):
        '''The STATUS command requests the status of the indicated mailbox.
        '''
        name = 'STATUS'
        
        self.sstatus['status_response'] = {}

        return self.processCommand( name, '"%s" %s' % (mailbox, 
            names))['status_response']
        
    def store(self, message_set, command, flags):
        '''Alters flag dispositions for messages in mailbox.
        
        Possible commands:
        
        FLAGS <flag list>
            Replace the flags for the message (other than \Recent) with the
            argument.  The new value of the flags is returned as if a FETCH
            of those flags was done.

        FLAGS.SILENT <flag list>
            Equivalent to FLAGS, but without returning a new value.

        +FLAGS <flag list>
            Add the argument to the flags for the message.  The new value
            of the flags is returned as if a FETCH of those flags was done.

        +FLAGS.SILENT <flag list>
            Equivalent to +FLAGS, but without returning a new value.

        -FLAGS <flag list>
            Remove the argument from the flags for the message.  The new
            value of the flags is returned as if a FETCH of those flags was
            done.

        -FLAGS.SILENT <flag list>
        '''
        
        name = 'STORE'
        
        flags = '(' + ' '.join(flags) + ')'
        
        if isinstance(message_set, list):
            message_set = ','.join( '%s' % Xi for Xi in message_set)
        
        return self.processCommand( name, '%s %s %s' % (message_set, 
            command, flags ))
        
    def subscribe(self, mailbox):
        '''
        '''
        name = 'SUBSCRIBE'
        
        return self.processCommand( name, '"%s"' % mailbox )
        
    def uid(self, command, args):
        '''UID based commands
        '''
        name = 'UID'
        
        return self.processCommand( name, '%s %s' % (command, args))
        
    def unsubscribe(self, mailbox):
        '''
        '''
        name = 'UNSUBSCRIBE'
        
        return self.processCommand( name, '"%s"' % (mailbox))
  
    ##
    # Helper methods
    ##
    
    def as_capability(self, capability ):
        '''Checks if the server has a given capability.
        
        @param capability: capability to test
        
        @return: true if the server has the capability, false otherwise.
        '''
        if not self.capabilities:
            self.capabilities = self.capability()
            
        return capability in self.capabilities
    
    ## UID commands
    def processCommandUID( self, name, args ):
        '''Process commands using the UID alternatives
        '''
        self._test_command('UID')
        self._test_command(name)
        
        command = 'UID %s %s' % (name, args)
        
        # Sends the command to the server, and parses the response
        tag, response = self.send_command(command)
        
        # Checks if the command was successfull
        if self._checkok(tag, response):
            return self.sstatus
        else:
            raise self.Error('Error in command UID %s - %s' % (name,
                response['tagged'][tag]['message']))
        
    def fetch_uid(self, message_list, message_parts='(FLAGS)' ):
        '''Fetch (parts of) messages, UID version.'''
        
        name = 'FETCH'
        
        self.sstatus['fetch_response'] = {}
        
        if isinstance(message_list, list) or \
           isinstance(message_list, tuple):
            message_list = shrink_fetch_list( message_list )
            message_list = ','.join( '%s' % Xi for Xi in message_list )
            
        args = '%s %s' % (message_list,  message_parts)
        
        result = self.processCommandUID(name, args)['fetch_response']

        tmp_result = {}
        for message in result.keys():
            tmp_result[result[message]['UID']] = result[message]
        del result
        
        return tmp_result
     
    def search_uid(self, criteria, charset=None):
        '''SEARCH command UID version'''
        
        name = 'SEARCH'
        self.sstatus['search_response'] = ()
        if charset:
            args = 'CHARSET %s %s' % (charset, criteria)
        else:
            args = criteria
        return self.processCommandUID(name, args)['search_response']
  
    def sort_uid(self, program, charset, search_criteria):
        '''SORT command returning UIDs (the server must support the UIDPLUS 
        extension.
        '''
        name = 'SORT'
        self.sstatus['sort_response'] = ()
        args = '%s %s %s' % (program, charset, search_criteria)
        return self.processCommandUID(name, args)['sort_response']
        
    ## SMART commands
    
    def _checkSort(self):
        if self.as_sort is None:
            self.as_sort = self.as_capability('SORT')
            
    def _checkUid(self):
        if self.as_uid is None:
            self.as_uid = self.as_capability('UIDPLUS')
    
    def sort_smart(self, program, charset, search_criteria):
        '''Same parameters as sort
        
        This command will try to use SORT to get the messages using UIDs, 
        if either extension is not available on the server, it will degrade to 
        the non UID SORT command or at worst to the SEARCH command. 
        FIXME: Note that for now, no attempt is made to emulate the 
        behaviour of the more complex commands on the degraded ones.
        '''
        self._checkSort()
        self._checkUid()
        if self.as_uid:
            if self.as_sort:
                return self.sort_uid(program, charset, search_criteria)
            else:
                return self.search_uid(search_criteria, charset)
        else:
            if self.as_sort:
                return self.sort(program, charset, search_criteria)
            else:
                return self.search(search_criteria, charset)
                
    def fetch_smart(self, message_list, message_parts='(FLAGS)' ):
        self._checkUid()
        if self.as_uid:
            return self.fetch_uid( message_list, message_parts )
        else:
            return self.fetch( message_list, message_parts )

if __name__ == '__main__':
    import getopt, getpass, sys
    
    try:
        optlist, args = getopt.getopt(sys.argv[1:], 'd:s:')
    except getopt.error, val:
        optlist, args = (), ()

    Debug = D_NOTPARSED
        
    if not args: args = ('',)

    host = args[0]

    USER = getpass.getuser()
    PASSWD = getpass.getpass("IMAP password for %s on %s: " % (USER, host or "localhost"))

    M = IMAP4P( host )
    
    M.login(USER, PASSWD)
    M.capability()
    M.logout()
    
    print '\n\nStatus:'
    
    import pprint
    pprint.pprint(M.sstatus)
    
    
