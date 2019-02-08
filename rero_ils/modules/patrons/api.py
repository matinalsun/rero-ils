# -*- coding: utf-8 -*-
#
# This file is part of RERO ILS.
# Copyright (C) 2017 RERO.
#
# RERO ILS is free software; you can redistribute it
# and/or modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# RERO ILS is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with RERO ILS; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place, Suite 330, Boston,
# MA 02111-1307, USA.
#
# In applying this license, RERO does not
# waive the privileges and immunities granted to it by virtue of its status
# as an Intergovernmental Organization or submit itself to any jurisdiction.

"""API for manipulating patrons."""

from functools import partial

from flask import current_app
from flask_login import current_user
from flask_security.confirmable import confirm_user
from flask_security.recoverable import send_reset_password_instructions
from invenio_accounts.ext import hash_password
from invenio_search.api import RecordsSearch
from werkzeug.local import LocalProxy
from werkzeug.utils import cached_property

from ..api import IlsRecord
from ..fetchers import id_fetcher
from ..minters import id_minter
from ..providers import Provider
from .models import PatronIdentifier

# from ..patron_types.api import PatronType

# from ..documents_items.api import DocumentsWithItems
# from ..documents.api import Document
# from ..libraries.api import Library
# from ..organisations_libraries.api import OrganisationWithLibraries
# from ..organisations.api import Organisation


_datastore = LocalProxy(lambda: current_app.extensions['security'].datastore)

current_patron = LocalProxy(lambda: Patron.get_patron_by_user(current_user))

# provider
PatronProvider = type(
    'PatronProvider',
    (Provider,),
    dict(identifier=PatronIdentifier, pid_type='ptrn')
)
# minter
patron_id_minter = partial(id_minter, provider=PatronProvider)
# fetcher
patron_id_fetcher = partial(id_fetcher, provider=PatronProvider)


class PatronsSearch(RecordsSearch):
    """PatronsSearch."""

    class Meta:
        """Search only on patrons index."""

        index = 'patrons'


class Patron(IlsRecord):
    """Define API for patrons mixing."""

    minter = patron_id_minter
    fetcher = patron_id_fetcher
    provider = PatronProvider
    available_roles = ['librarian', 'patron']

    @classmethod
    def create(cls, data, id_=None, delete_pid=True,
               dbcommit=False, reindex=False, **kwargs):
        """."""
        record = super(Patron, cls).create(
            data, id_, delete_pid, dbcommit, reindex, **kwargs)
        record._update_roles()
        return record

    def delete(self, force=False, delindex=False):
        """Delete record and persistent identifier."""
        self._remove_roles()
        super(Patron, self).delete(force, delindex)
        return self

    def update(self, data, dbcommit=False, reindex=False):
        """Update data for record."""
        super(Patron, self).update(data, dbcommit, reindex)
        self._update_roles()
        return self

    @cached_property
    def user(self):
        """."""
        email = self.get('email')
        user = _datastore.find_user(email=email)
        if not user:
            password = hash_password(email)

            _datastore.create_user(email=email, password=password)
            _datastore.commit()
            # send password reset
            user = _datastore.find_user(email=email)
            send_reset_password_instructions(user)
            confirm_user(user)
        return user

    def _update_roles(self):
        """."""
        db_roles = self.user.roles
        for role in self.available_roles:
            in_db = role in db_roles
            in_record = role in self.get('roles', [])
            if in_record and not in_db:
                self.add_role(role)
            if not in_record and in_db:
                self.remove_role(role)

    def _remove_roles(self):
        """."""
        db_roles = self.user.roles
        for role in self.available_roles:
            if role in db_roles:
                self.remove_role(role)

    @classmethod
    def get_patron_by_user(cls, user):
        """Get patron by user."""
        if hasattr(user, 'email'):
            return cls.get_patron_by_email(email=user.email)

    @classmethod
    def get_patron_by_email(cls, email=None):
        """Get patron by email."""
        pid_value = cls.get_pid_by_email(email)
        if pid_value:
            return cls.get_record_by_pid(pid_value)
        else:
            return None

    @classmethod
    def get_pid_by_email(cls, email):
        """Get uuid pid by email."""
        result = PatronsSearch().filter(
            'term',
            email=email
        ).source(includes='pid').scan()
        try:
            return next(result).pid
        except StopIteration:
            return None

    @classmethod
    def get_patron_by_barcode(cls, barcode=None):
        """Get patron by barcode."""
        search = PatronsSearch()
        result = search.filter(
            'term',
            barcode=barcode
        ).source(includes='pid').scan()
        try:
            patron_pid = next(result).pid
            return super(Patron, cls).get_record_by_pid(patron_pid)
        except StopIteration:
            return None

    # @classmethod
    # def delete_by_email(cls, email, deluser=False, delindex=False):
    #     """Delete user by email."""
    #     patron = cls.get_patron_by_email(email)
    #     if patron:
    #         patron.delete(delindex)
    #     datastore = LocalProxy(
    #         lambda: current_app.extensions['security'].datastore
    #     )
    #     user = datastore.find_user(email=email)
    #     if user:
    #         datastore.delete_user(user)
    #         datastore.commit()

    # def get_borrowed_documents_pids(self):
    #     """Get pid values borrowed documents for given patron."""

    #     loans = get_loans_by_patron_pid(self.pid)
    #     pids = []
    #     if loans:
    #         pids = [loan.document_pid for loan in loans]
    #     return pids

    # def get_loaned_documents(self):
    #     """Get borrowed documents."""
    #     pids = self.get_borrowed_documents_pids()
    #     to_return = []
    #     for pid_value in pids:
    #         rec = Document.get_record_by_pid(pid_value)
    #         # rec = DocumentsWithItems.get_record_by_pid(pid_value)
    #         to_return.append(rec)
    #     return to_return

    def add_role(self, role_name):
        """Add a given role to a user."""
        role = _datastore.find_role(role_name)
        _datastore.add_role_to_user(self.user, role)
        _datastore.commit()

    def remove_role(self, role_name):
        """Remove a given role from a user."""
        role = _datastore.find_role(role_name)
        _datastore.remove_role_from_user(self.user, role)
        _datastore.commit()

    # def has_role(self, role_name):
    #     """Check if a user has a given role."""
    #     email = self.get('email')
    #     user = _datastore.find_user(email=email)
    #     # role = _datastore.find_role(role_name)
    #     return user.has_role(role_name)

    # def get_one_pickup_location(self):
    #     """Find a qualified pickup location."""
    #     library_pid = self.get('library_pid')
    #     from ..libraries.api import Library
    #     library = Library.get_record_by_pid(library_pid)
    #     locations = library.pickup_locations
    #     return locations[0]['pid']

    # def dumps(self, **kwargs):
    #     """Return pure Python dictionary with record metadata."""
    #     data = super(Patron, self).dumps(**kwargs)
    #     data['roles'] = self.role_names
    #     data['name'] = ', '.join((
    #         data.get('last_name', ''),
    #         data.get('first_name', '')
    #     ))
    #     if data.get('is_patron', True):
    #         data['circulation_location_pid'] = self.get_one_pickup_location()
    #     if data.get('is_patron', False):
    #         patron_type = PatronType.get_record_by_pid(
    #            data['patron_type_pid'])
    #         data['patron_type'] = patron_type.get('name')
    #     if (self.organisation):
    #         data['organisation_pid'] = self.organisation.pid
    #     return data

    # @property
    # def can_delete(self):
    #     """Record can be deleted."""
    #     return len(self.get_borrowed_documents_pids()) == 0

    # @property
    # def roles(self):
    #     """Return user roles."""
    #     email = self.get('email')
    #     user = _datastore.find_user(email=email)
    #     if user:
    #         return user.roles
    #     return []

    # @property
    # def barcode(self):
    #     """Return user barcode."""
    #     return self.get('barcode')

    # @property
    # def role_names(self):
    #     """Return user role names."""
    #     return [v.name for v in self.roles]

    # @property
    # def library(self):
    #     """Get library."""
    #     library_pid = self.get('library_pid')
    #     return Library.get_record_by_pid(library_pid)

    # @property
    # def organisation(self):
    #     """Get organisation."""
    #     if self.library:
    #         return Organisation.get_organisation_by_libraryid(
    #             self.library.id
    #         )
    #     return None

    # @property
    # def name(self):
    #     """Return the full name of the patron."""
    #     my_name = '{first_name} {last_name}'.format(
    #         first_name=self['first_name'],
    #         last_name=self['last_name']
    #     )
    #     return my_name

    @property
    def initial(self):
        """Return the initials of the patron first name."""
        initial = ''
        firsts = self['first_name'].split(' ')
        for first in firsts:
            initial += first[0]
        lasts = self['last_name'].split(' ')
        for last in lasts:
            if last[0].isupper():
                initial += last[0]

        return initial