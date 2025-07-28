
from odoo import models, fields, api
import re

class LibrayManagement(models.Model):
    _name = 'library.book'
    _description = 'Book in the library'

    title = fields.Char(string="Title", required=True)
    author = fields.Char(string="Author")
    isbn = fields.Char(string="ISBN", size=17, help="13-Digits ISBN number")
    publication_date = fields.Date(string="Publication Date")

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
        return super(LibrayManagement, self).create(vals)