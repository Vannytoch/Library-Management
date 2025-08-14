from odoo import models, fields, api

class RentalReport(models.AbstractModel):
    _name = 'report.library_management.report_rental_template'
    _description = 'Rental Report Template'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['library.rental'].browse(docids)

        start_date = None
        end_date = None

        if data and data.get('form'):
            start_date = data['form'].get('start_date')
            end_date = data['form'].get('end_date')
            docs = self.env['library.rental'].search([
                ('rental_date', '>=', start_date),
                ('rental_date', '<=', end_date)
            ])
        return {
            'doc_ids': docids,
            'doc_model': 'library.rental',
            'docs': docs,
            'start_date': start_date,
            'end_date': end_date,
            'data': data,
        }