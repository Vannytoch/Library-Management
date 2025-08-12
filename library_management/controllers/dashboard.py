from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request
from odoo import http
from datetime import datetime
from dateutil.relativedelta import relativedelta

class LibraryDashboardPortal(CustomerPortal):

    @http.route(['/my/library'], type='http', website=True)
    def libraryDashboardView(self, **kw):
        books = request.env['library.book']
        rentals = request.env['library.rental']
        books_field_status = books._fields['status'].selection
        status_book={}
        for book in books_field_status:
            status_book[book[1]] = books.search_count([('status', '=', book[0])])
        type_book={}
        books_field_type = books._fields['genre'].selection
        for type in books_field_type:
            type_book[type[1]] = books.search_count([('genre', '=', type[0])])

        rental_per_mount = {}
        today = datetime.today()
        for i in range(6):
            month_start = today - relativedelta(months=i)
            first_day = month_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_day_date = first_day + relativedelta(months=1, days=-1)
            rental_per_mount[month_start.strftime('%B')] = rentals.search_count([
                ('rental_date', '>=', first_day),
                ('rental_date', '<=', last_day_date)
            ])
        rental_field_state = rentals._fields['state'].selection
        rental_state_count ={}
        for state in rental_field_state:
            rental_state_count[state[1]] = rentals.search_count([('state', '=', state[0])])

        data = {
            'book_status_count': status_book,
            'book_genre_count': type_book,
            'rental_per_mount': rental_per_mount,
            'rental_state_count': rental_state_count,
            'page_name':'library_dashboard'
        }

        return request.render('library_management.library_dashboard_template', data)