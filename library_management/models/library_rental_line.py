from email.policy import default

from odoo import models, fields, api

class LibraryRentalLine(models.Model):
    _name = 'library.rental.line'
    _description = 'This line for only library rental'

    rental_id = fields.Many2one(
        comodel_name='library.rental',
        string="Rental Reference",
        required=True, ondelete='cascade', index=True, copy=False)
    sequence = fields.Integer(string="Sequence", default=10)
    book_id = fields.Many2one('library.book', string='Book')
    qty = fields.Integer(string='Quantity', default=1)
    unit_price = fields.Float(
        string='Unit Price',
        compute='_compute_unit_price',
        readonly=True,
        required=True,
        currency_field='rental_id.currency_id'
    )
    discount = fields.Float(
        string='Discount (%)',
    )
    subtotal = fields.Float(
        string='Amount',
        compute='_compute_subtotal',
        readonly=True,
        currency_field = 'rental_id.currency_id'
    )
    excluded_book_ids = fields.Many2many(
        'library.book',
        compute='_compute_excluded_book_ids',
        store=False
    )

    @api.depends('rental_id.rental_line_ids')
    def _compute_excluded_book_ids(self):
        for line in self:
            if line.rental_id:
                line.excluded_book_ids = line.rental_id.rental_line_ids.mapped('book_id')
            else:
                line.excluded_book_ids = False

    @api.depends('book_id')
    def _compute_unit_price(self):
        for rec in self:
            if rec.book_id:
                rec.unit_price = rec.book_id.rental_fee
            else:
                rec.unit_price = 0.00

    @api.depends('book_id', 'unit_price', 'qty', 'discount')
    def _compute_subtotal(self):
        for rec in self:
            if rec.book_id:
                total = rec.unit_price * rec.qty
                if rec.discount:
                    discount = total * rec.discount/100
                    total = total-discount
                rec.subtotal = total
            else:
                rec.subtotal = 0.00

