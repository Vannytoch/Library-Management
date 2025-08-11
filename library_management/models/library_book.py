from markupsafe import Markup
from odoo import models, fields, api
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
        readonly=True,
        required=True
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
                        ('state', 'not in', ['returned', 'draft'])
                    ])
                    if rental:
                        vals.pop('status')
                        raise UserError("Cannot mark as 'available': The book is currently rented and lost.")

        for rec in self:
            if 'status' in vals and vals['status'] in ['borrowed', 'lost']:
                rental = self.env['library.rental'].search([
                    ('state', 'not in', ['returned', 'draft']),
                    ('book_ids', '=', rec.id)
                ], limit=1)
                vals['member_id'] = rental.member_id if rental else False
            else:
                vals['member_id'] = False

        res = super().write(vals)
        return res
