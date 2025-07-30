from email.policy import default

from odoo import models, fields, api
from datetime import date
from dateutil.relativedelta import relativedelta
import re

class LibraryManagement(models.Model):
    _name = 'library.book'
    _description = 'Book in the library'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    title = fields.Char(string="Title", required=True)
    isbn = fields.Char(string="ISBN", size=17, help="13-Digits ISBN number")
    publication_date = fields.Date(string="Publication Date")
    author_id = fields.Many2one('library.author', string="Author")
    image_1920 = fields.Binary(string="Cover image")
    book_age = fields.Integer(string="Book Age (Years)", compute="_compute_book_age", store=True)
    member_id = fields.Many2one('library.member',tracking=False,  string="Borrowed By")
    status = fields.Selection([
        ('available', 'Available'),
        ('borrowed', 'Borrowed'),
        ('lost', 'Lost')
    ], string="Status", default='available',
        required=True, group_expand="_read_group_stage_ids")
    genre = fields.Selection([
        ('fiction', 'Fiction'),
        ('nonfiction', 'Non-Fiction'),
        ('fantasy', 'Fantasy'),
        ('biography', 'Biography'),
        ('science', 'Science'),
    ], string="Genre")

    @api.onchange('member_id')
    def compute_status(self):
        if self.status == 'lost':
            return  # Don't change lost status
        if not self.member_id:
            self.status = 'available'
        else:
            self.with_context(from_member_form=True).write({'status':'borrowed'})

    @api.depends('publication_date')
    def _compute_book_age(self):
        today = fields.Date.today()
        for record in self:
            if record.publication_date:
                record.book_age = today.year - record.publication_date.year
            else:
                record.book_age = 0

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return [key for key, _ in self._fields['status'].selection]

    @api.onchange('status')
    def _onchange_status_form(self):
        if self.status == "borrowed":
            members = self.env['library.member'].search([('book_id.id', '=', self.id)])
            if not members:
                default_member = self.env['library.member'].search([], limit=1)
                if default_member:
                    default_member.book_id = [(4, self.id)]
            else:
                for member in members:
                    member.book_id = [(4, self.id)]
        elif self.status == 'available':
            if self.member_id:
                self.member_id = False
        elif self.status == "lost" :
            return

    def _onchange_status(self, val):

        if self.status == "borrowed" and val == "available":
            members = self.env['library.member'].search([('book_id.id', '=', self.id)])
            for member in members:
                # remove this book from the member's book_id (One2many)
                member.book_id = [(3, self.id)]
        elif self.status == "lost" and val == "available":
            if self.member_id:
                self.member_id = False

        print("\n\n\n\nHello\n\n\n\n")


    @api.onchange('isbn')
    def _onchange_isbn(self):
        if self.isbn:
            # Remove all non-digit characters
            digits = re.sub(r'\D', '', self.isbn)

            if len(digits) == 13:
                # Format as 978-3-16-148410-0
                self.isbn = f"{digits[0:3]}-{digits[3]}-{digits[4:6]}-{digits[6:12]}-{digits[12]}"
            else:
                self.isbn=digits
                return {
                    'warning': {
                        'title': "Invalid ISBN",
                        'message': "ISBN must contain exactly 13 digits.",
                    }
                }

    @api.model
    def create(self, vals):
        if 'isbn' in vals and vals['isbn']:
            digits = re.sub(r'\D', '', vals['isbn'])  # Remove all non-digit characters
            if len(digits) == 13:
                vals['isbn'] = digits  # Store plain 13-digit value
            else:
                del vals['isbn']
        for record in self:
            if 'member_id' in vals:
                member_id = vals['member_id']
                member = self.env['library.member'].browse(member_id)
                record.message_post(
                    body=f"This 📘 Book borrowed by: {member.name}"
                )

        return super(LibraryManagement, self).create(vals)

    @api.model
    def write(self, vals):
        if 'status' in vals:
            if not self.env.context.get('from_member_form'):
                # block status change from Kanban or other views
                if (self.status == "available" and vals['status'] == "borrowed") or (self.status == "lost" and vals['status'] == "borrowed"):
                    if 'member_id' not in vals:
                        vals.pop('status')
                else:
                    self._onchange_status(vals['status'])
            else:
                self._onchange_status(vals['status'])
        for record in self:
            if 'member_id' in vals:
                new_member_id = vals['member_id']  # New value being written
                old_member = record.member_id  # Current value before change

                if not new_member_id and old_member:
                    # Book is being returned
                    record.message_post(
                        body=f"This 📘 Book returned by: {old_member.name}"
                    )
                elif not old_member and new_member_id:
                    # Book is being borrowed
                    new_member = self.env['library.member'].browse(new_member_id)
                    record.message_post(
                        body=f"This 📘 Book borrowed by: {new_member.name}"
                    )
                elif new_member_id != old_member.id:
                    # Member changed: first return, then borrow
                    record.message_post(
                        body=f"This 📘 Book returned by: {old_member.name}"
                    )
                    new_member = self.env['library.member'].browse(new_member_id)
                    record.message_post(
                        body=f"This 📘 Book borrowed by: {new_member.name}"
                    )

        return super(LibraryManagement, self).write(vals)


class Author(models.Model):
    _name = 'library.author'
    _description = 'Author write book in this library'

    name = fields.Char(string="Author Name")
    age = fields.Integer(string="Age")
    email = fields.Char(string="Email")
    dob = fields.Date(string="Date of Birth")
    pob = fields.Text(string="Place of Birth")

    @api.onchange('email')
    def onchange_email(self):
        if self.email:
            # Simple email format validation using regex
            pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
            if not re.match(pattern, self.email):
                return {
                    'warning': {
                        'title': "Invalid Email Format",
                        'message': "Please enter a valid email address (e.g., user@example.com)."
                    }
                }
class Member(models.Model):
    _name = 'library.member'
    _description = 'Member come to our library.'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Name", required=True)
    dob = fields.Date(string="Date of Birth")
    gender = fields.Selection(string="Gender", selection=[('male', 'Male'), ('female', 'Female')], default="male")
    image_1920 = fields.Binary(string="Photo")
    email = fields.Char(string="Email", required=True)
    address = fields.Text(string="Address")
    membership_id = fields.Char(
        string="Membership ID",
        compute='_compute_membership_id',
        store=True,
        readonly=True,
    )
    membership_type = fields.Selection([
    ('student', 'Student'),
    ('teacher', 'Teacher'),
    ('public', 'Public'),
    ('child', 'Child'),
    ('vip', 'VIP')], string="Membership Type", default="public")
    expiry_date = fields.Date(
        string="Expiry Date",
        default=lambda self: date.today() + relativedelta(years=1)
    )
    contact = fields.Char(string="Emergency Contact")
    institution = fields.Char(string="Institution")
    book_id = fields.One2many(
        'library.book',  # target model
        'member_id',  # inverse field (many2one field in `library.book`)
        string="Book",
        tracking=False,
    )
    available_book_ids = fields.Many2many('library.book', compute='_compute_available_books')

    @api.depends('membership_id')
    def _compute_available_books(self):
        # Search all available books

        book_ids = self.book_id.ids
        if book_ids:
            domain = ['|', ('id', 'in', book_ids), ('status', '=', 'available')]
        else:
            domain = [('status', '=', 'available')]

        available_book_ids = self.env['library.book'].search(domain)
        for member in self:
            member.available_book_ids = available_book_ids

    @api.depends('expiry_date')
    def _compute_membership_id(self):
        for record in self:
            if not record.membership_id:
                year_str = str(date.today().year)
                prefix = 'M' + year_str

                # Find last membership_id for this year (ignore current record)
                last_member = self.search(
                    [('membership_id', 'ilike', prefix), ('id', '!=', record.id)],
                    order='membership_id desc',
                    limit=1
                )
                if last_member:
                    last_id = last_member.membership_id
                    last_number = int(last_id[len(prefix):])
                    new_number = last_number + 1
                else:
                    new_number = 1

                record.membership_id = f"{prefix}{new_number:05d}"

    @api.onchange('email')
    def onchange_email(self):
        if self.email:
            # Simple email format validation using regex
            pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
            if not re.match(pattern, self.email):
                return {
                    'warning': {
                        'title': "Invalid Email Format",
                        'message': "Please enter a valid email address (e.g., user@example.com)."
                    }
                }

    @api.model
    def create(self, vals):
        if vals.get('membership_id', 'New') == 'New':
            year_str = str(date.today().year)
            prefix = 'M' + year_str

            last_member = self.search([('membership_id', 'ilike', prefix)], order='membership_id desc', limit=1)
            if last_member:
                last_number = int(last_member.membership_id[len(prefix):])
                new_number = last_number + 1
            else:
                new_number = 1
            vals['membership_id'] = f"{prefix}{new_number:05d}"

        result = super(Member, self).create(vals)

        for record in result:
            if 'book_id' in vals and vals['book_id']:
                new_books = record.book_id.ids
                for book in record.book_id:
                    book.status = 'borrowed'

                book_names = self.env['library.book'].browse(new_books).mapped('title')
                record.message_post(
                    body=f"📘 Member borrowed book(s) at registration: <b>{', '.join(book_names)}</b>"
                )
        return result

    @api.model
    def write(self, vals):
        # Since `self` can contain multiple records, we track all old book IDs by record ID
        old_book_map = {rec.id: rec.book_id.ids for rec in self}

        result = super(Member, self).write(vals)
        for record in self:
            print(f"\n\n\n\n Write of Member is work")
            if 'book_id' in vals:
                old_books = set(old_book_map.get(record.id, []))
                new_books = set(record.book_id.ids)

                added_books_ids = list(new_books - old_books)
                removed_books_ids = list(old_books - new_books)

                if added_books_ids:
                    added_books = self.env['library.book'].browse(added_books_ids)
                    book_names = added_books.mapped('title')
                    record.message_post(
                        body=f"📘 Member borrowed new book(s): <b>{', '.join(book_names)}</b>"
                    )
                    added_books.with_context(from_member_form=True).write({'status': 'borrowed'})

                if removed_books_ids:
                    removed_books = self.env['library.book'].browse(removed_books_ids)
                    book_names = removed_books.mapped('title')
                    record.message_post(
                        body=f"📤 Member returned book(s): <b>{', '.join(book_names)}</b>"
                    )
                    removed_books.with_context(from_member_form=True).write({'status': 'available'})

        return result
