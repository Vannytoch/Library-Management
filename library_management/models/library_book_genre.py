from odoo import models, fields, api

class BookGenre(models.Model):
    _name = 'library.book.genre'
    _description = 'Genre of books'

    name = fields.Char(string='Name', required=True)
