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
# $LastChangedDate: 2008-04-18 13:11:56 +0100 (Fri, 18 Apr 2008) $
# $LastChangedRevision: 322 $
# $LastChangedBy: helder $
# 

# Imports

import base64

# Attributes:

NOSELECT = r'\Noselect'
HASCHILDREN = r'\HasChildren'
HASNOCHILDREN = r'\HasNoChildren'

class Mailbox:
    def __init__(self, name, attributes, delimiter):
        self.name = name
        self.delimiter = delimiter
        self.attributes = attributes
        
    def test_attribute(self, attr ):
        return attr in self.attributes
        
    def noselect(self):
        return self.test_attribute(NOSELECT)
        
    def level(self):
        return len(self.name)-1
        
    def last_level(self):
        return self.name[-1]
        
    def native(self):
        '''Return the mailbox in raw format using the delimiter
        understood by the server.
        '''
        
        return self.get_str(self.delimiter)
                    
    def url(self):
        '''Return the folder name on a url safe way
        '''
        return base64.urlsafe_b64encode(self.get_str(self.delimiter))
        
    def get_str(self, delimiter='.'):
        '''Return the mailbox name using the supplied delimiter
        '''
        if self.delimiter:
            return delimiter.join(self.name)
        else:
            return self.name
        
    def __str__(self):
        return self.native()
        
    
class ListParser:
    def __init__(self):
        self.hierarchy_delimiter = None
        self.mailbox_list = []
        
        self.index = 0
        
    def add_folder( self, name, attributes ):
        self.mailbox_list.append( 
            Mailbox(name, attributes,self.hierarchy_delimiter ))
        
    def set_delimiter( self, hierarchy_delimiter ):
        if not self.hierarchy_delimiter:
            self.hierarchy_delimiter = hierarchy_delimiter
            
    def __str__(self):
        return '<ListParser "%s" %d mailboxes>' % (self.hierarchy_delimiter,
            len(self.mailbox_list))
      
    # List behaviour
    def __getitem__(self, index):
        return self.mailbox_list[index]

    # Iterator
    def __iter__(self):
        return iter(self.mailbox_list)
        
 
            
        
