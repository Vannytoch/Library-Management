from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request
from odoo import http

class LibraryPortal(CustomerPortal):


    @http.route(['/my/library/rental'], type='http', website=True)
    def libraryListView(self, **kw):
        rentals = request.env['library.rental'].sudo().search([])
        return request.render('library_management.library_rental_list_view_portal', {'rentals': rentals, 'page_name': 'rental_list_view'})
    @http.route(['/my/library/rental/<model("library.rental"):rental_id>'], type='http', website=True)
    def libraryFormView(self, rental_id, **kw):
        vals = {
                'rental': rental_id,
                'page_name':'rental_form_view'
            }
        return request.render('library_management.library_rental_form_view_portal', vals)