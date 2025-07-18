import base64
import os.path
from email.policy import default

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError, AccessError
import time
import re



class Qrcode(models.Model):
    _name="account.qrcode"
    _description="QR code for invoice"

    name=fields.Char(string="Qr code name")
    image=fields.Image(string="Qr code image")

class AccountMoveInherit(models.Model):
    _inherit= "account.move"

    def action_print_invoice(self):
        self.ensure_one()
        if not self.env.user.has_group('qr_code.group_can_print_invoice'):
            raise AccessError("You do not have permission to print invoices.")
        return self.env.ref('Invoice_pdf_report.account_invoice_custom_report').report_action(self)

    #
    # @api.onchange('qrcode_id')
    # def _update_qrcode(self):
    #     for recode in self:
    #         if recode.qrcode_id and recode.qrcode_id.image:
    #             recode.qrcode = recode.qrcode_id.image
    #         else:
    #             recode.qrcode = False
    #
    # @api.model
    # def create(self, vals):
    #     if vals.get('qrcode_id'):
    #         qrcode_record = self.env['account.qrcode'].browse(vals['qrcode_id'])
    #         if qrcode_record.image:
    #             vals['qrcode'] = qrcode_record.image
    #     return super().create(vals)
    #
    # def write(self, vals):
    #     if 'qrcode_id' in vals:
    #         qrcode_record = self.env['account.qrcode'].browse(vals['qrcode_id'])
    #         if qrcode_record.image:
    #             vals['qrcode'] = qrcode_record.image
    #         else:
    #             vals['qrcode'] = False
    #     return super().write(vals)

    # create invoice
    # step 1 default Qrcode
    # step 2 set to qrcode (account.move)

