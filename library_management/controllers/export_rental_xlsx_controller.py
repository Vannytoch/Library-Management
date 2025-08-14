from odoo import http
from odoo.http import request
import io
import openpyxl
from datetime import datetime
from openpyxl.styles import Alignment

class RentalReportController(http.Controller):

    @http.route('/library/export_rental_xlsx', type='http', auth='user')
    def export_rental_xlsx(self, start_date=None, end_date=None, state=None, **kwargs):
        # Filter data
        Rental = request.env['library.rental'].sudo()
        domain = []
        if start_date and end_date:
            domain.append(('rental_date', '>=', start_date))
            domain.append(('rental_date', '<=', end_date))
        if state:
            state_list = state.split(',')  # Convert from "draft,confirmed"
            domain.append(('state', 'in', state_list))

        rentals = Rental.search(domain)

        # Create XLSX
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Rental Report'
        ws.append(['Number', 'Due Date', 'Member', 'Rental Date', 'Rental Fee', 'Return Date', 'Status', 'Book Title', 'Quantity', 'Discount'])

        ws.column_dimensions['A'].width = 30  # Book Title
        ws.column_dimensions['B'].width = 30  # Date
        ws.column_dimensions['C'].width = 30  # Customer
        ws.column_dimensions['D'].width = 30  # Start
        ws.column_dimensions['E'].width = 30  # Fee
        ws.column_dimensions['F'].width = 30  # Return
        ws.column_dimensions['G'].width = 30  # State
        ws.column_dimensions['H'].width = 30  # State
        ws.column_dimensions['I'].width = 30  # State
        ws.column_dimensions['J'].width = 30  # State


        for r in rentals:
            for i, line in enumerate(r.rental_line_ids):
                if i == 0:
                    ws.append([r.name, r.due_date, r.member_id.name, r.rental_date, r.total_amount, r.return_date, r.state,
                               line.book_id.title, line.qty, line.discount])
                else:
                    ws.append(['', '', '', '', '', '', '', line.book_id.title, line.qty, line.discount])

        wrap_alignment = Alignment(wrap_text=True)
        for row in ws.iter_rows(min_row=2):  # Skip header row
            book_cell = row[7]  # Column A
            if book_cell.value:
                book_cell.alignment = wrap_alignment
        fp = io.BytesIO()
        wb.save(fp)
        fp.seek(0)
        xlsx_data = fp.read()
        fp.close()

        filename = f"rental_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        headers = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', f'attachment; filename="{filename}"')
        ]
        return request.make_response(xlsx_data, headers)
