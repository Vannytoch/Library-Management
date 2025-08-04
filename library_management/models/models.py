
from markupsafe import Markup

from odoo import models, fields, api
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError
import re


class LibraryManagement(models.Model):
    _name = 'library.book'
    _description = 'Book in the library'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'title'

    title = fields.Char(string="Title", required=True)
    isbn = fields.Char(string="ISBN", size=17, help="13-Digits ISBN number")
    publication_date = fields.Date(string="Publication Date")
    author_id = fields.Many2one('library.author', string="Author")
    image_1920 = fields.Binary(string="Cover image")
    book_age = fields.Integer(string="Book Age (Years)", compute="_compute_book_age", store=True)
    member_id = fields.Many2one('library.member',tracking=True, string="Borrowing by")


    rental_fee = fields.Monetary(string="Rental Fee", default=1.0)
    currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        compute='_compute_currency',
        store=True,
        readonly=True
    )



    total_rental = fields.Float(string="Total Rental", compute="_compute_total_rental", store=True)
    status = fields.Selection([
        ('available', 'Available'),
        ('borrowed', 'Borrowed'),
        ('lost', 'Lost')
    ], string="Status", default='available',
        tracking=True,
        required=True, group_expand="_read_group_stage_ids")
    genre = fields.Selection([
        ('fiction', 'Fiction'),
        ('nonfiction', 'Non-Fiction'),
        ('fantasy', 'Fantasy'),
        ('biography', 'Biography'),
        ('science', 'Science'),
    ], string="Genre")

    @api.depends('member_id', 'message_ids')
    def _compute_total_rental(self):
        pattern = re.compile(r'Rental fee:\s*\$?([0-9,.]+)')
        for book in self:
            total = 0.0
            for msg in book.message_ids:
                if msg.body:
                    # Search for "Rental fee: $xxx.xx" pattern
                    match = pattern.search(msg.body)
                    if match:
                        # Remove commas and convert to float
                        amount_str = match.group(1).replace(',', '')
                        try:
                            amount = float(amount_str)
                            total += amount
                        except ValueError:
                            pass
            book.total_rental = total

    @api.depends()
    def _compute_currency(self):
        for record in self:
            record.currency_id = self.env.company.currency_id

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
                    body=Markup(
                        f"<h3>This 📘 Book borrowed by: {new_member.name} <br/>Rental fee: {record.currency_id.symbol}{record.rental_fee}</h3>")
                )

        return super(LibraryManagement, self).create(vals)

    @api.model
    def write(self, vals):
        for record in self:
            if 'status' in vals and not self.env.context.get('from_member_form'):
                if (vals['status'] == 'available' and record.status == 'borrowed') \
                        or (vals['status'] == 'borrowed' and record.status == 'available'):
                    vals.pop('status')
                    raise UserError("Invalid status change: Cannot switch directly between 'borrowed' and 'available'.")

                elif vals['status'] == 'borrowed' and record.status == 'lost':
                    rental = self.env['library.rental'].search([
                        ('book_ids', 'in', record.id),
                        ('state', '!=', 'returned')
                    ])
                    if not rental:
                        vals.pop('status')
                        raise UserError("Cannot mark as 'borrowed': This book has not been rented.")

                elif vals['status'] == 'available' and record.status == 'lost':
                    rental = self.env['library.rental'].search([
                        ('book_ids', 'in', record.id),
                        ('state', '!=', 'returned')
                    ])
                    if rental:
                        vals.pop('status')
                        raise UserError("Cannot mark as 'available': The book is currently rented and lost.")

        for rec in self:
            if 'status' in vals and vals['status'] in ['borrowed', 'lost']:
                rental = self.env['library.rental'].search([
                    ('state', '!=', 'returned'),
                    ('book_ids', '=', rec.id)
                ], limit=1)
                vals['member_id'] = rental.member_id if rental else False
            else:
                vals['member_id'] = False

        # l-b some
        # l-b some

        # l-a some
        # l-a some ok

        # b-l
        # a-l
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
    total_rental = fields.Float(string="Total Rental", compute="_compute_total_rental", store=True)
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

    @api.depends('book_id', 'message_ids')
    def _compute_total_rental(self):
        pattern = re.compile(r'-\s*\$?\s*([0-9,.]+)')
        for book in self:
            total = 0.0
            for msg in book.message_ids:
                if msg.body:
                    # Search for "Rental fee: $xxx.xx" pattern
                    match = pattern.search(msg.body)
                    if match:
                        # Remove commas and convert to float
                        amount_str = match.group(1).replace(',', '')
                        try:
                            amount = float(amount_str)
                            total += amount
                        except ValueError:
                            pass
            book.total_rental = total

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
    def create(self, vals_list):
        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        for vals in vals_list:
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

        records = super(Member, self).create(vals_list)

        for record in records:
            if record.book_id:
                lines = []
                for book in record.book_id:
                    symbol = book.currency_id.symbol or ''
                    lines.append(f"- {book.title} - {symbol}{book.rental_fee:.2f}")
                    book.status = 'borrowed'
                message = "📘 Member borrowed book(s) at registration:<br/>" + "<br/>".join(lines)
                record.message_post(body=Markup(message))

        return records

    def write(self, vals):
        old_book_map = {rec.id: rec.book_id.ids for rec in self}

        result = super(Member, self).write(vals)

        for record in self:
            if 'book_id' in vals:
                old_books = set(old_book_map.get(record.id, []))
                new_books = set(record.book_id.ids)

                added_book_ids = list(new_books - old_books)
                removed_book_ids = list(old_books - new_books)

                if added_book_ids:
                    added_books = self.env['library.book'].browse(added_book_ids)
                    lines = []
                    for book in added_books:
                        symbol = book.currency_id.symbol or ''
                        lines.append(f"- {book.title} - {symbol}{book.rental_fee:.2f}")
                    added_books.with_context(from_member_form=True).write({'status': 'borrowed'})
                    message = "📘 Member borrowed new book(s):<br/>" + "<br/>".join(lines)
                    record.message_post(body=Markup(message))

                if removed_book_ids:
                    removed_books = self.env['library.book'].browse(removed_book_ids)
                    book_names = removed_books.mapped('title')
                    removed_books.with_context(from_member_form=True).write({'status': 'available'})
                    message = "📤 Member returned book(s): <b>" + ", ".join(book_names) + "</b>"
                    record.message_post(body=Markup(message))

        return result
class RentalSystem(models.Model):
    _name = 'library.rental'
    _description = 'Rental System of Library'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Enables chatter + activity tracking
    _order = 'rental_date desc'


    member_id = fields.Many2one('library.member', string="Member", required=True, tracking=True)
    book_ids = fields.Many2many(
        'library.book',  # target model
        string="Book",
        tracking=True,
        required=True,
    )
    rental_date = fields.Date(string="Rental Date", default=fields.Date.context_today, required=True, tracking=True)
    due_date = fields.Date(string="Due Date", required=True, tracking=True)
    return_date = fields.Date(string="Return Date", tracking=True)
    rental_fee = fields.Monetary(
        string="Rental Fee",
        currency_field='currency_id',
        compute='_compute_rental_fee',
        tracking=True
    )
    total_rental = fields.Monetary(
        string="Total Rental",
        currency_field='currency_id',
        tracking=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('active', 'Active'),
        ('returned', 'Returned'),
        ('overdue', 'Overdue'),
    ], string="Status", default='draft', tracking=True,)

    available_book_ids = fields.Many2many('library.book', compute='_compute_available_books')
    is_visible_due = fields.Date(default=date.today(), required=True)

    def action_send_mail_rental(self):
        import logging
        _logger = logging.getLogger(__name__)
        template = self.env.ref('library_management.email_template_rental_overdue', raise_if_not_found=False)
        print("\n\n\nHello me\n\n\n\n")

        if not template:
            _logger.warning("Email template NOT found: library_management.email_template_rental_overdue")
        else:
            template.send_mail(self.id, force_send=True)
            if self.member_id.email:
                print("\n\n\n",self.member_id.email,"\n\n\n\n")

    @api.model
    def update_overdue_states(self):
        today = fields.Date.today()
        overdue_rentals = self.search([
            ('due_date', '<', today),
            ('return_date', '=', False),
            ('state', '!=', 'returned')
        ])
        for rental in overdue_rentals:
            rental.state = 'overdue'

    @api.depends('state', 'book_ids')
    def _compute_available_books(self):
        # Search all available books
        book_ids = self.book_ids.ids
        if book_ids:
            domain = ['|', ('id', 'in', book_ids), ('status', '=', 'available')]
        else:
            domain = [('status', '=', 'available')]

        available_book_ids = self.env['library.book'].search(domain)
        for member in self:
            member.available_book_ids = available_book_ids


    @api.depends('book_ids')
    def _compute_rental_fee(self):
        for record in self:
            record.rental_fee = sum(book.rental_fee for book in record.book_ids)

    # Automatically compute overdue status
    @api.onchange('due_date', 'return_date')
    def _check_overdue(self):
        for record in self:
            if record.state in ('active', 'confirmed') and record.due_date and not record.return_date:
                if fields.Date.context_today(record) > record.due_date:
                    record.state = 'overdue'

    @api.model
    def create(self, vals):
        res = super().create(vals)

        if 'book_ids' in vals and vals.get('member_id'):
            book_ids = []

            # Handle different command types in the many2many field
            for command in vals['book_ids']:
                if command[0] == 4:  # Link to existing record
                    book_ids.append(command[1])
                elif command[0] == 6:  # Replace all with new list of IDs
                    book_ids.extend(command[2])

            if book_ids:
                books = self.env['library.book'].browse(book_ids)
                books.with_context(from_member_form=True).write({
                    'status': 'borrowed',
                    'member_id': vals['member_id']
                })

        return res

    @api.model
    def write(self, vals):
        # Keep track of added and removed book IDs
        added_books = set()
        removed_books = set()

        # Handle changes in book_ids
        if 'book_ids' in vals:
            for command in vals['book_ids']:
                if command[0] == 4:  # Add single book
                    added_books.add(command[1])
                elif command[0] == 3:  # Remove single book
                    removed_books.add(command[1])
                elif command[0] == 6:  # Replace all
                    new_ids = set(command[2])
                    old_ids = set(self.book_ids.ids)
                    added_books |= new_ids - old_ids
                    removed_books |= old_ids - new_ids

        # Apply status changes for added/removed books
        if added_books:
            self.env['library.book'].browse(list(added_books)).with_context(from_member_form=True).write(
                {'status': 'borrowed'})
        if removed_books:
            self.env['library.book'].browse(list(removed_books)).with_context(from_member_form=True).write(
                {'status': 'available'})

        # Call super to write vals
        result = super().write(vals)

        # Handle state change to 'returned'
        if 'state' in vals and vals['state'] == 'returned':
            for rec in self:
                rec.book_ids.with_context(from_member_form=True).write({'status': 'available'})

        return result

    # State transition methods
    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only Draft rentals can be confirmed.")
            if rec.due_date - rec.rental_date < timedelta(days=1):
                raise UserError("The rental period must be at least 1 full day.")
            if rec.return_date:
                raise UserError("Return date must be clear before confirm.")
            rec.state = 'confirmed'

    def action_start(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError("Only Confirmed rentals can be started.")
            rec.state = 'active'

    def action_return(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Return Rentals',
            'res_model': 'library.rental.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_rental_ids': self.ids,
            }
        }
        # for rec in self:
        #     if rec.state not in ('active', 'overdue'):
        #         raise UserError("Only Active or Overdue rentals can be returned.")
        #     if rec.return_date and rec.return_date < rec.rental_date:
        #         raise UserError("Can't returned, Check rental date and currently date.")
        #     rec.state = 'returned'
        #     rec.return_date = fields.Date.today()

    def action_mark_overdue(self):
        for rec in self:
            if rec.state != 'active':
                raise UserError("Only Active rentals can be marked overdue.")
            rec.state = 'overdue'

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('confirmed', 'active', 'returned', 'overdue'):
                raise UserError("Can only reset from Confirmed, Active, Returned, or Overdue states.")
            rec.state = 'draft'
            rec.rental_date = date.today()
            rec.due_date = date.today() + relativedelta(months=1)
            rec.return_date = False


class LibraryRentalReturnWizard(models.TransientModel):
    _name = 'library.rental.return.wizard'
    _description = 'Bulk Rental Return Wizard'

    rental_ids = fields.Many2many('library.rental', string='Rentals to Return', required=True)

    def confirm_returns(self):
        for rental in self.rental_ids:
            if rental.state not in ('active', 'overdue'):
                raise UserError("Only Active or Overdue rentals can be returned.")
            if rental.return_date and rental.return_date < rental.rental_date:
                raise UserError("Can't return, Check rental date and current date.")
            rental.state = 'returned'
            rental.return_date = fields.Date.today()
        return {'type': 'ir.actions.act_window_close'}
