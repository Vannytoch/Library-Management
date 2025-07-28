from odoo import Command, _, fields, models, api
from odoo.tools import float_repr
from collections import defaultdict
from odoo.tools.float_utils import float_repr, float_round


class AccountTaxInherit(models.Model):
    _inherit = 'account.tax'

    @api.model
    def _prepare_base_line_for_taxes_computation_custom(self, record, **kwargs):

        result = super()._prepare_base_line_for_taxes_computation(record, **kwargs)
        def load(field, fallback, from_base_line=False):
            return self._get_base_line_field_value_from_record(record, field, kwargs, fallback,
                                                               from_base_line=from_base_line)
        result['discount'] = load('custom_discount', 0.0)
        return result


    def total_price(self, baseline):
        total = 0.0
        for line in baseline:
            total += line['quantity'] * line['price_unit']
        return total

    @api.model
    def _get_tax_totals_summary(self, base_lines, currency, company, cash_rounding=None):
        tax_totals_summary = super()._get_tax_totals_summary(base_lines, currency,company, cash_rounding)
        tax_totals_summary['total_before_discount'] = self.total_price(base_lines)
        tax_totals_summary['discount_total'] =\
            tax_totals_summary['total_before_discount'] - tax_totals_summary['base_amount']
        return tax_totals_summary

class QuotationDiscountInherit(models.Model):
    _inherit=['sale.order']

    discount_choose = fields.Selection(
        selection=[('Custom', 'Custom Discount'), ('Original', 'Original Discount')],
        string="Discount Type:",
        default="Custom",
        store=True
    )
    discount_amount = fields.Float(string="Discount Amount:")

    @api.depends_context('lang')
    @api.depends('order_line.price_subtotal','order_line.price_unit', 'order_line.custom_discount', 'order_line.discount','discount_choose', 'currency_id', 'company_id', 'payment_term_id')
    def _compute_tax_totals(self):
        AccountTax = self.env['account.tax']
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            if(order.discount_choose=="Original"):
                base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]
            else:
                base_lines = [line._prepare_base_line_for_taxes_computation_custom() for line in order_lines]
            base_lines += order._add_base_lines_for_early_payment_discount()
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            order.tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
            )

    @api.depends('order_line.price_subtotal', 'currency_id', 'company_id', 'payment_term_id')
    def _compute_amounts(self):
        AccountTax = self.env['account.tax']
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            if (order.discount_choose == "Original"):
                base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]
            else:
                base_lines = [line._prepare_base_line_for_taxes_computation_custom() for line in order_lines]
            base_lines += order._add_base_lines_for_early_payment_discount()
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            tax_totals = AccountTax._get_tax_totals_summary(
                base_lines=base_lines,
                currency=order.currency_id or order.company_id.currency_id,
                company=order.company_id,
            )
            order.amount_untaxed = tax_totals['base_amount_currency']
            order.amount_tax = tax_totals['tax_amount_currency']
            order.amount_total = tax_totals['total_amount_currency']
            order.discount_amount = order.process_discount_amount() - order.amount_total

    @api.depends('order_line.custom_discount')
    def _onchange_custom_discount(self):
        self._compute_tax_totals()

    @api.onchange('discount_choose')
    def onchange_discount_choose(self):
        self.order_line._compute_amount()
        self._compute_tax_totals()

    def action_open_discount_wizard(self):
        self.discount_choose = 'Original'
        return super().action_open_discount_wizard()

    def button_discount_custom(self):
        self.discount_choose = 'Custom'
        return {
            'type': 'ir.actions.act_window',
            'name': 'Custom Wizard Discount',
            'res_model': 'sale.discount.custom',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_order_id': self.id  # pass active order
            }
        }

    def process_discount_amount(self):
        discount = 0.0
        for order in self:
            for line in order.order_line:
                discount += line.price_unit * line.product_uom_qty
        return discount


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    custom_discount = fields.Float(string="Discount Amount(%)")


    def _prepare_base_line_for_taxes_computation_custom(self, **kwargs):
        """ Convert the current record to a dictionary in order to use the generic taxes computation method
        defined on account.tax.

        :return: A python dictionary.
        """
        self.ensure_one()
        return self.env['account.tax']._prepare_base_line_for_taxes_computation_custom(
            self,
            **{
                'tax_ids': self.tax_id,
                'quantity': self.product_uom_qty,
                'partner_id': self.order_id.partner_id,
                'currency_id': self.order_id.currency_id or self.order_id.company_id.currency_id,
                'rate': self.order_id.currency_rate,
                **kwargs,
            },
        )

    @api.onchange('custom_discount')
    def onchange_custom_discount(self):
        for order in self:
            order.order_id.discount_choose = 'Custom'

    @api.onchange('discount')
    def onchange_discount(self):
        for order in self:
            order.order_id.discount_choose = 'Original'

    @api.depends('price_unit', 'product_uom_qty','order_id.discount_choose', 'custom_discount', 'tax_id')
    def _compute_amount(self):
        for line in self:
            if (line.order_id.discount_choose == "Original"):
                base_line = line._prepare_base_line_for_taxes_computation()
            else:
                base_line = line._prepare_base_line_for_taxes_computation_custom()
            self.env['account.tax']._add_tax_details_in_base_line(base_line, line.company_id)
            line.price_subtotal = base_line['tax_details']['raw_total_excluded_currency']
            line.price_total = base_line['tax_details']['raw_total_included_currency']
            line.price_tax = line.price_total - line.price_subtotal
            line.order_id.discount_amount = line.order_id.process_discount_amount() - line.order_id.amount_total

class SaleCustomDiscount(models.TransientModel):
    _name = 'sale.discount.custom'
    _description = 'Apply Discount to Quotation.'

    order_id = fields.Many2one('sale.order', string="Quotation")
    custom_discount = fields.Float(string="Discount Amount(%)")
    line_ids = fields.Many2many('sale.order.line', string="Select products")
    check_all = fields.Boolean(string="Check All",store=False)

    def apply_discount(self):
        for line in self.line_ids:
            line.custom_discount = self.custom_discount
        self.line_ids._compute_amount()
        self.order_id._compute_tax_totals()
        return {'type': 'ir.actions.act_window_close'}

    @api.onchange('check_all')
    def _onchange_check_all(self):
        if not self.order_id:
            return

        lines = self.env['sale.order.line'].search([
            ('order_id', '=', self.order_id.id),
            ('display_type', 'not in', ['line_section', 'line_note'])
        ])
        for wizard in self:
            if wizard.check_all:
                wizard.line_ids = [(6, 0, lines.ids)]  # Select all
            else:
                wizard.line_ids = [(6, 0, [])]  # Uncheck all

    @api.onchange('order_id')
    def _onchange_order_id(self):
        for wizard in self:
            wizard.line_ids = False  # Clear selection initially
