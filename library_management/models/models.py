
from odoo import models, fields, api
import re

class LibrayManagement(models.Model):
    _name = 'library.book'
    _description = 'Book in the library'

    title = fields.Char(string="Title", required=True)
    isbn = fields.Char(string="ISBN", size=17, help="13-Digits ISBN number")
    publication_date = fields.Date(string="Publication Date")
    author_id = fields.Many2one('library.author', string="Author")
    image_1920 = fields.Binary(string="Cover image")
    book_age = fields.Integer(string="Book Age (Years)", compute="_compute_book_age", store=True)
    status = fields.Selection([
        ('available', 'Available'),
        ('borrowed', 'Borrowed'),
        ('lost', 'Lost')
    ], string="Status", default='available', required=True, group_expand="_read_group_stage_ids")
    genre = fields.Selection([
        ('fiction', 'Fiction'),
        ('nonfiction', 'Non-Fiction'),
        ('fantasy', 'Fantasy'),
        ('biography', 'Biography'),
        ('science', 'Science'),
    ], string="Genre")



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
        return super(LibrayManagement, self).create(vals)


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