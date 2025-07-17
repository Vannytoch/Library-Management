from odoo import models, fields, api


class AccountInvoicePrinting(models.Model):
    _inherit= "account.move"

    def get_data_invoice(self):
        qrcode_record = self.env['account.qrcode']
        data={
            'qrcode_record' : qrcode_record.search([], limit=1).image
        }
        return data