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
    rental_fee = fields.Monetary(string="Rental Fee", default=1.0, tracking=True)
    stock = fields.Integer(string='In stock', default=1)
    book_genre = fields.Many2one('library.book.genre', string="Genre")
    currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        compute='_compute_currency',
        store=True,
        readonly=True,
        required=True
    )
    status = fields.Selection([
        ('in_stock', 'In stock'),
        ('out_stock', 'Out stock'),
    ], string="Status",
        compute='_compute_status',
        store=True,
        tracking=True,
        required=True,
        group_expand="_read_group_stage_ids"
    )

    @api.depends('rental_fee')
    def _compute_currency(self):
        for record in self:
            record.currency_id = self.env.company.currency_id
    @api.depends('stock')
    def _compute_status(self):
        for rec in self:
            if rec.stock > 0:
                rec.status = 'in_stock'
            else:
                rec.status = 'out_stock'
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

