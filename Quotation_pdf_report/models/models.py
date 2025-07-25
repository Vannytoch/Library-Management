from odoo import Command, _, fields, models, api
from odoo.tools import float_repr
from odoo.exceptions import ValidationError
from collections import defaultdict
from odoo.tools.float_utils import float_repr, float_round, float_compare
import logging
_logger = logging.getLogger(__name__)


class AccountTaxInherit(models.Model):
    _inherit = 'account.tax'

    @api.model
    def _prepare_base_line_for_taxes_computation_custom(self, record, **kwargs):
        """ Convert any representation of a business object ('record') into a base line being a python
        dictionary that will be used to use the generic helpers for the taxes computation.

        The whole method is designed to ease the conversion from a business record.
        For example, when passing either account.move.line, either sale.order.line or purchase.order.line,
        providing explicitely a 'product_id' in kwargs is not necessary since all those records already have
        an `product_id` field.

        :param record:  A representation of a business object a.k.a a record or a dictionary.
        :param kwargs:  The extra values to override some values that will be taken from the record.
        :return:        A dictionary representing a base line.
        """

        def load(field, fallback, from_base_line=False):
            return self._get_base_line_field_value_from_record(record, field, kwargs, fallback,
                                                               from_base_line=from_base_line)

        currency = (
                load('currency_id', None)
                or load('company_currency_id', None)
                or load('company_id', self.env['res.company']).currency_id
                or self.env['res.currency']
        )

        return {
            **kwargs,
            'record': record,
            'id': load('id', 0),

            # Basic fields:
            'product_id': load('product_id', self.env['product.product']),
            'product_uom_id': load('product_uom_id', self.env['uom.uom']),
            'tax_ids': load('tax_ids', self.env['account.tax']),
            'price_unit': load('price_unit', 0.0),
            'quantity': load('quantity', 0.0),
            'discount': load('custom_discount', 0.0),
            # 'discount': load('discount', 0.0),
            'currency_id': currency,

            # The special_mode for the taxes computation:
            # - False for the normal behavior.
            # - total_included to force all taxes to be price included.
            # - total_excluded to force all taxes to be price excluded.
            'special_mode': load('special_mode', False, from_base_line=True),

            # A special typing of base line for some custom behavior:
            # - False for the normal behavior.
            # - early_payment if the base line represent an early payment in mixed mode.
            # - cash_rounding if the base line is a delta to round the business object for the cash rounding feature.
            'special_type': load('special_type', False, from_base_line=True),

            # All computation are managing the foreign currency and the local one.
            # This is the rate to be applied when generating the tax details (see '_add_tax_details_in_base_line').
            'rate': load('rate', 1.0),

            # For all computation that are inferring a base amount in order to reach a total you know in advance, you have to force some
            # base/tax amounts for the computation (E.g. down payment, combo products, global discounts etc).
            'manual_tax_amounts': load('manual_tax_amounts', None, from_base_line=True),

            # Add a function allowing to filter out some taxes during the evaluation. Those taxes can't be removed from the base_line
            # when dealing with group of taxes to maintain a correct link between the child tax and its parent.
            'filter_tax_function': load('filter_tax_function', None, from_base_line=True),

            # ===== Accounting stuff =====

            # The sign of the business object regarding its accounting balance.
            'sign': load('sign', 1.0),

            # If the document is a refund or not to know which repartition lines must be used.
            'is_refund': load('is_refund', False),

            # If the tags must be inverted or not.
            'tax_tag_invert': load('tax_tag_invert', False),

            # Extra fields for tax lines generation:
            'partner_id': load('partner_id', self.env['res.partner']),
            'account_id': load('account_id', self.env['account.account']),
            'analytic_distribution': load('analytic_distribution', None),
        }

    def total_price(self, baseline):
        total = 0.0
        for line in baseline:
            total += line['quantity'] * line['price_unit']
        return total
    @api.model
    def _get_tax_totals_summary(self, base_lines, currency, company, cash_rounding=None):
        """ Compute the tax totals details for the business documents.

        Don't forget to call '_add_tax_details_in_base_lines' and '_round_base_lines_tax_details' before calling this method.

        :param base_lines:          A list of base lines generated using the '_prepare_base_line_for_taxes_computation' method.
        :param currency:            The tax totals is only available when all base lines share the same currency.
                                    Since the tax totals can be computed when there is no base line at all, a currency must be
                                    specified explicitely for that case.
        :param company:             The company owning the base lines.
        :param cash_rounding:       A optional account.cash.rounding object. When specified, the delta base amount added
                                    to perform the cash rounding is specified in the results.
        :return: A dictionary containing:
            currency_id:                            The id of the currency used.
            currency_pd:                            The currency rounding (to be used js-side by the widget).
            company_currency_id:                    The id of the company's currency used.
            company_currency_pd:                    The company's currency rounding (to be used js-side by the widget).
            has_tax_groups:                         Flag indicating if there is at least one involved tax group.
            same_tax_base:                          Flag indicating the base amount of all tax groups are the same and it's
                                                    redundant to display them.
            base_amount_currency:                   The untaxed amount expressed in foreign currency.
            base_amount:                            The untaxed amount expressed in local currency.
            tax_amount_currency:                    The tax amount expressed in foreign currency.
            tax_amount:                             The tax amount expressed in local currency.
            total_amount_currency:                  The total amount expressed in foreign currency.
            total_amount:                           The total amount expressed in local currency.
            cash_rounding_base_amount_currency:     The delta added by 'cash_rounding' expressed in foreign currency.
                                                    If there is no amount added, the key is not in the result.
            cash_rounding_base_amount:              The delta added by 'cash_rounding' expressed in local currency.
                                                    If there is no amount added, the key is not in the result.
            subtotals:                              A list of subtotal (like "Untaxed Amount"), each one being a python dictionary
                                                    containing:
                base_amount_currency:                   The base amount expressed in foreign currency.
                base_amount:                            The base amount expressed in local currency.
                tax_amount_currency:                    The tax amount expressed in foreign currency.
                tax_amount:                             The tax amount expressed in local currency.
                tax_groups:                             A list of python dictionary, one for each tax group, containing:
                    id:                                     The id of the account.tax.group.
                    group_name:                             The name of the group.
                    group_label:                            The short label of the group to be displayed on POS receipt.
                    involved_tax_ids:                       A list of the tax ids aggregated in this tax group.
                    base_amount_currency:                   The base amount expressed in foreign currency.
                    base_amount:                            The base amount expressed in local currency.
                    tax_amount_currency:                    The tax amount expressed in foreign currency.
                    tax_amount:                             The tax amount expressed in local currency.
                    display_base_amount_currency:           The base amount to display expressed in foreign currency.
                                                            The flat base amount and the amount to be displayed are sometimes different
                                                            (e.g. division/fixed taxes).
                    display_base_amount:                    The base amount to display expressed in local currency.
                                                            The flat base amount and the amount to be displayed are sometimes different
                                                            (e.g. division/fixed taxes).
        """

        tax_totals_summary = {
            'currency_id': currency.id,
            'currency_pd': currency.rounding,
            'company_currency_id': company.currency_id.id,
            'company_currency_pd': company.currency_id.rounding,
            'has_tax_groups': False,
            'subtotals': [],
            'base_amount_currency': 0.0,
            'base_amount': 0.0,
            'tax_amount_currency': 0.0,
            'tax_amount': 0.0,
            'discount_total': 0.0,
            'total_before_discount':0.0,

        }

        # Global tax values.
        def global_grouping_function(base_line, tax_data):
            return True if tax_data else None

        base_lines_aggregated_values = self._aggregate_base_lines_tax_details(base_lines, global_grouping_function)
        values_per_grouping_key = self._aggregate_base_lines_aggregated_values(base_lines_aggregated_values)
        for grouping_key, values in values_per_grouping_key.items():
            if grouping_key:
                tax_totals_summary['has_tax_groups'] = True
            tax_totals_summary['base_amount_currency'] += values['total_excluded_currency']
            tax_totals_summary['base_amount'] += values['total_excluded']
            tax_totals_summary['tax_amount_currency'] += values['tax_amount_currency']
            tax_totals_summary['tax_amount'] += values['tax_amount']

        tax_totals_summary['total_before_discount'] = self.total_price(base_lines)
        tax_totals_summary['discount_total'] = tax_totals_summary['total_before_discount'] - tax_totals_summary['base_amount']


        # Tax groups.
        untaxed_amount_subtotal_label = _("Untaxed Amount")
        subtotals = defaultdict(lambda: {
            'tax_groups': [],
            'tax_amount_currency': 0.0,
            'tax_amount': 0.0,
            'base_amount_currency': 0.0,
            'base_amount': 0.0,
        })

        def tax_group_grouping_function(base_line, tax_data):
            return tax_data['tax'].tax_group_id if tax_data else None

        base_lines_aggregated_values = self._aggregate_base_lines_tax_details(base_lines, tax_group_grouping_function)
        values_per_grouping_key = self._aggregate_base_lines_aggregated_values(base_lines_aggregated_values)
        sorted_total_per_tax_group = sorted(
            [values for grouping_key, values in values_per_grouping_key.items() if grouping_key],
            key=lambda values: (values['grouping_key'].sequence, values['grouping_key'].id),
        )

        encountered_base_amounts = set()
        subtotals_order = {}

        for order, values in enumerate(sorted_total_per_tax_group):

            tax_group = values['grouping_key']

            # Get all involved taxes in the tax group.
            involved_taxes = self.env['account.tax']
            for base_line, taxes_data in values['base_line_x_taxes_data']:
                for tax_data in taxes_data:
                    involved_taxes |= tax_data['tax']

            # Compute the display base amounts.
            display_base_amount = values['base_amount']
            display_base_amount_currency = values['base_amount_currency']
            if set(involved_taxes.mapped('amount_type')) == {'fixed'}:
                display_base_amount = None
                display_base_amount_currency = None
            elif set(involved_taxes.mapped('amount_type')) == {'division'} and all(
                    involved_taxes.mapped('price_include')):
                for base_line, _taxes_data in values['base_line_x_taxes_data']:
                    for tax_data in base_line['tax_details']['taxes_data']:
                        if tax_data['tax'].amount_type == 'division':
                            display_base_amount_currency += tax_data['tax_amount_currency']
                            display_base_amount += tax_data['tax_amount']

            if display_base_amount_currency is not None:
                encountered_base_amounts.add(float_repr(display_base_amount_currency, currency.decimal_places))

            # Order of the subtotals.
            preceding_subtotal = tax_group.preceding_subtotal or untaxed_amount_subtotal_label
            if preceding_subtotal not in subtotals_order:
                subtotals_order[preceding_subtotal] = order
            subtotals[preceding_subtotal]['tax_groups'].append({
                'id': tax_group.id,
                'involved_tax_ids': involved_taxes.ids,
                'tax_amount_currency': values['tax_amount_currency'],
                'tax_amount': values['tax_amount'],
                'base_amount_currency': values['base_amount_currency'],
                'base_amount': values['base_amount'],
                'display_base_amount_currency': display_base_amount_currency,
                'display_base_amount': display_base_amount,
                'group_name': tax_group.name,
                'group_label': tax_group.pos_receipt_label,
            })

        # Subtotals.
        if not subtotals:
            subtotals[untaxed_amount_subtotal_label]
        ordered_subtotals = sorted(subtotals.items(), key=lambda item: subtotals_order.get(item[0], 0))
        accumulated_tax_amount_currency = 0.0
        accumulated_tax_amount = 0.0
        for subtotal_label, subtotal in ordered_subtotals:
            subtotal['name'] = subtotal_label
            subtotal['base_amount_currency'] = tax_totals_summary[
                                                   'base_amount_currency'] + accumulated_tax_amount_currency
            subtotal['base_amount'] = tax_totals_summary['base_amount'] + accumulated_tax_amount

            for tax_group in subtotal['tax_groups']:
                subtotal['tax_amount_currency'] += tax_group['tax_amount_currency']
                subtotal['tax_amount'] += tax_group['tax_amount']
                accumulated_tax_amount_currency += tax_group['tax_amount_currency']
                accumulated_tax_amount += tax_group['tax_amount']

            tax_totals_summary['subtotals'].append(subtotal)

        # Cash rounding
        cash_rounding_lines = [base_line for base_line in base_lines if base_line['special_type'] == 'cash_rounding']
        if cash_rounding_lines:
            tax_totals_summary['cash_rounding_base_amount_currency'] = 0.0
            tax_totals_summary['cash_rounding_base_amount'] = 0.0
            for base_line in cash_rounding_lines:
                tax_details = base_line['tax_details']
                tax_totals_summary['cash_rounding_base_amount_currency'] += tax_details['total_excluded_currency']
                tax_totals_summary['cash_rounding_base_amount'] += tax_details['total_excluded']
        elif cash_rounding:
            strategy = cash_rounding.strategy
            cash_rounding_pd = cash_rounding.rounding
            cash_rounding_method = cash_rounding.rounding_method
            total_amount_currency = tax_totals_summary['base_amount_currency'] + tax_totals_summary[
                'tax_amount_currency']
            total_amount = tax_totals_summary['base_amount'] + tax_totals_summary['tax_amount']
            expected_total_amount_currency = float_round(
                total_amount_currency,
                precision_rounding=cash_rounding_pd,
                rounding_method=cash_rounding_method,
            )
            cash_rounding_base_amount_currency = expected_total_amount_currency - total_amount_currency
            rate = abs(total_amount_currency / total_amount) if total_amount else 0.0
            cash_rounding_base_amount = company.currency_id.round(
                cash_rounding_base_amount_currency / rate) if rate else 0.0
            if not currency.is_zero(cash_rounding_base_amount_currency):
                if strategy == 'add_invoice_line':
                    tax_totals_summary['cash_rounding_base_amount_currency'] = cash_rounding_base_amount_currency
                    tax_totals_summary['cash_rounding_base_amount'] = cash_rounding_base_amount
                    tax_totals_summary['base_amount_currency'] += cash_rounding_base_amount_currency
                    tax_totals_summary['base_amount'] += cash_rounding_base_amount
                    subtotals[untaxed_amount_subtotal_label][
                        'base_amount_currency'] += cash_rounding_base_amount_currency
                    subtotals[untaxed_amount_subtotal_label]['base_amount'] += cash_rounding_base_amount
                elif strategy == 'biggest_tax':
                    all_subtotal_tax_group = [
                        (subtotal, tax_group)
                        for subtotal in tax_totals_summary['subtotals']
                        for tax_group in subtotal['tax_groups']
                    ]

                    if all_subtotal_tax_group:
                        max_subtotal, max_tax_group = max(
                            all_subtotal_tax_group,
                            key=lambda item: item[1]['tax_amount_currency'],
                        )
                        max_tax_group['tax_amount_currency'] += cash_rounding_base_amount_currency
                        max_tax_group['tax_amount'] += cash_rounding_base_amount
                        max_subtotal['tax_amount_currency'] += cash_rounding_base_amount_currency
                        max_subtotal['tax_amount'] += cash_rounding_base_amount
                        tax_totals_summary['tax_amount_currency'] += cash_rounding_base_amount_currency
                        tax_totals_summary['tax_amount'] += cash_rounding_base_amount
                    else:
                        # Failed to apply the cash rounding since there is no tax.
                        cash_rounding_base_amount_currency = 0.0
                        cash_rounding_base_amount = 0.0

        # Subtract the cash rounding from the untaxed amounts.
        cash_rounding_base_amount_currency = tax_totals_summary.get('cash_rounding_base_amount_currency', 0.0)
        cash_rounding_base_amount = tax_totals_summary.get('cash_rounding_base_amount', 0.0)
        tax_totals_summary['base_amount_currency'] -= cash_rounding_base_amount_currency
        tax_totals_summary['base_amount'] -= cash_rounding_base_amount
        for subtotal in tax_totals_summary['subtotals']:
            subtotal['base_amount_currency'] -= cash_rounding_base_amount_currency
            subtotal['base_amount'] -= cash_rounding_base_amount
        encountered_base_amounts.add(float_repr(tax_totals_summary['base_amount_currency'], currency.decimal_places))
        tax_totals_summary['same_tax_base'] = len(encountered_base_amounts) == 1

        # Total amount.
        tax_totals_summary['total_amount_currency'] = \
            tax_totals_summary['base_amount_currency'] + tax_totals_summary[
                'tax_amount_currency'] + cash_rounding_base_amount_currency
        tax_totals_summary['total_amount'] = \
            tax_totals_summary['base_amount'] + tax_totals_summary['tax_amount'] + cash_rounding_base_amount

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

    def _add_base_lines_for_early_payment_discount_custom(self):
        """
        When applying a payment term with an early payment discount, and when said payment term computes the tax on the
        'mixed' setting, the tax computation is always based on the discounted amount untaxed.
        Creates the necessary line for this behavior to be displayed.
        :returns: array containing the necessary lines or empty array if the payment term isn't epd mixed
        """
        self.ensure_one()
        epd_lines = []
        if (
            self.payment_term_id.early_discount
            and self.payment_term_id.early_pay_discount_computation == 'mixed'
            and self.payment_term_id.discount_percentage
        ):
            percentage = self.payment_term_id.discount_percentage
            currency = self.currency_id or self.company_id.currency_id
            for line in self.order_line.filtered(lambda x: not x.display_type):
                line_amount_after_discount = (line.price_subtotal / 100) * percentage
                epd_lines.append(self.env['account.tax']._prepare_base_line_for_taxes_computation_custom(
                    record=self,
                    price_unit=-line_amount_after_discount,
                    quantity=1.0,
                    currency_id=currency,
                    sign=1,
                    special_type='early_payment',
                    tax_ids=line.tax_id,
                ))
                epd_lines.append(self.env['account.tax']._prepare_base_line_for_taxes_computation_custom(
                    record=self,
                    price_unit=line_amount_after_discount,
                    quantity=1.0,
                    currency_id=currency,
                    sign=1,
                    special_type='early_payment',
                ))
        return epd_lines

    @api.depends_context('lang')
    @api.depends('order_line.price_subtotal','order_line.price_unit', 'order_line.custom_discount', 'order_line.discount','discount_choose', 'currency_id', 'company_id', 'payment_term_id')
    def _compute_tax_totals(self):
        AccountTax = self.env['account.tax']
        for order in self:
            order_lines = order.order_line.filtered(lambda x: not x.display_type)
            if(order.discount_choose=="Original"):
                base_lines = [line._prepare_base_line_for_taxes_computation() for line in order_lines]
                base_lines += order._add_base_lines_for_early_payment_discount()
            else:
                base_lines = [line._prepare_base_line_for_taxes_computation_custom() for line in order_lines]
                base_lines += order._add_base_lines_for_early_payment_discount_custom()

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
                base_lines += order._add_base_lines_for_early_payment_discount()
            else:
                base_lines = [line._prepare_base_line_for_taxes_computation_custom() for line in order_lines]
                base_lines += order._add_base_lines_for_early_payment_discount_custom()
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
        self.ensure_one()
        return {
            'name': _("Discount"),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.discount',
            'view_mode': 'form',
            'target': 'new',
        }

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
