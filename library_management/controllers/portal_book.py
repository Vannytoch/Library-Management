from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request
from odoo import http

class LibraryBookPortal(CustomerPortal):

    @http.route(['/my/library/book'], type='http', website=True)
    def libraryBookListView(self, **kw):
        books = request.env['library.book'].sudo().search([])
        return request.render('library_management.library_book_list_view_portal', {'books': books, 'page_name': 'library_books'})
    @http.route(['/my/library/book/<model("library.book"):book_id>'], type='http', website=True)
    def libraryBookFormView(self, book_id, **kw):
        vals = {
                'book': book_id,
                'page_name':'book_form_view'
            }
        return request.render('library_management.library_book_form_view_portal', vals)