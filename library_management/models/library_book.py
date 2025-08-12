from markupsafe import Markup
from odoo import models, fields, api
from odoo.exceptions import UserError
import re

class LibraryManagement(models.Model):
    _name = 'library.book'
    _description = 'Book in the library'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'title'

    title = fields.Char(string="Title", required=True, tracking=True)
    isbn = fields.Char(string="ISBN", size=17, help="13-Digits ISBN number")
    publication_date = fields.Date(string="Publication Date")
    author_id = fields.Many2one('library.author', string="Author", tracking=True)
    image_1920 = fields.Binary(string="Cover image")
    book_age = fields.Integer(string="Book Age (Years)", compute="_compute_book_age", store=True)
    member_id = fields.Many2one('library.member',tracking=True, string="Borrowing by")
    rental_fee = fields.Monetary(string="Rental Fee", default=1.0, tracking=True)
    total_rental = fields.Float(string="Total Rental", compute="_compute_total_rental", store=True)
    currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        compute='_compute_currency',
        store=True,
        readonly=True,
        required=True
    )
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

    @api.depends('member_id', 'message_ids', 'status')
    def _compute_total_rental(self):
        rentals = self.env['library.rental'].search_count([('book_ids', 'in', self.id), ('state', '!=', 'draft')])
        self.total_rental = rentals * self.rental_fee

    @api.depends('rental_fee')
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
                        ('state', 'not in', ['returned', 'draft'])
                    ])
                    if rental:
                        vals.pop('status')
                        raise UserError("Cannot mark as 'available': The book is currently rented and lost.")
            elif 'status' in vals and self.env.context.get('from_member_form'):
                for rec in self:
                    if 'status' in vals and vals['status'] in ['borrowed', 'lost']:
                        rental = self.env['library.rental'].search([
                            ('state', 'not in', ['draft', 'returned']),
                            ('book_ids', '=', rec.id)
                        ], limit=1)
                        if rental:
                            vals['member_id'] = rental.member_id
                        else:
                            if vals['status'] == 'borrowed' and rec.status == 'lost':
                                raise UserError("Not sure member for rental")
                    else:
                        vals['member_id'] = False
        res = super().write(vals)
        return res
