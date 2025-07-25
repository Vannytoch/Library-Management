from odoo import Command, _, fields, models, api
from odoo.tools import float_repr
from odoo.exceptions import ValidationError
from collections import defaultdict
from odoo.tools.float_utils import float_repr, float_round, float_compare
import math
import logging
_logger = logging.getLogger(__name__)
import time

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

    # def custom_compute_all(self, price_unit, currency=None, quantity=1.0, product=None, partner=None, is_refund=False,
    #                        handle_price_include=True, include_caba_tags=False, rounding_method=None):
    #     """Compute all information required to apply taxes (in self + their children in case of a tax group).
    #     We consider the sequence of the parent for group of taxes.
    #         Eg. considering letters as taxes and alphabetic order as sequence :
    #         [G, B([A, D, F]), E, C] will be computed as [A, D, F, C, E, G]
    #
    #
    #
    #     :param price_unit: The unit price of the line to compute taxes on.
    #     :param currency: The optional currency in which the price_unit is expressed.
    #     :param quantity: The optional quantity of the product to compute taxes on.
    #     :param product: The optional product to compute taxes on.
    #         Used to get the tags to apply on the lines.
    #     :param partner: The optional partner compute taxes on.
    #         Used to retrieve the lang to build strings and for potential extensions.
    #     :param is_refund: The optional boolean indicating if this is a refund.
    #     :param handle_price_include: Used when we need to ignore all tax included in price. If False, it means the
    #         amount passed to this method will be considered as the base of all computations.
    #     :param include_caba_tags: The optional boolean indicating if CABA tags need to be taken into account.
    #     :return: {
    #         'total_excluded': 0.0,    # Total without taxes
    #         'total_included': 0.0,    # Total with taxes
    #         'total_void'    : 0.0,    # Total with those taxes, that don't have an account set
    #         'base_tags: : list<int>,  # Tags to apply on the base line
    #         'taxes': [{               # One dict for each tax in self and their children
    #             'id': int,
    #             'name': str,
    #             'amount': float,
    #             'base': float,
    #             'sequence': int,
    #             'account_id': int,
    #             'refund_account_id': int,
    #             'analytic': bool,
    #             'price_include': bool,
    #             'tax_exigibility': str,
    #             'tax_repartition_line_id': int,
    #             'group': recordset,
    #             'tag_ids': list<int>,
    #             'tax_ids': list<int>,
    #         }],
    #     } """
    #     if not self:
    #         company = self.env.company
    #     else:
    #         company = self[0].company_id._accessible_branches()[:1] or self[0].company_id
    #
    #     # Compute tax details for a single line.
    #     currency = currency or company.currency_id
    #     if 'force_price_include' in self._context:
    #         special_mode = 'total_included' if self._context['force_price_include'] else 'total_excluded'
    #     elif not handle_price_include:
    #         special_mode = 'total_excluded'
    #     else:
    #         special_mode = False
    #     base_line = self._prepare_base_line_for_taxes_computation_custom(
    #         None,
    #         partner_id=partner,
    #         currency_id=currency,
    #         product_id=product,
    #         tax_ids=self,
    #         price_unit=price_unit,
    #         quantity=quantity,
    #         is_refund=is_refund,
    #         special_mode=special_mode,
    #     )
    #     self._add_tax_details_in_base_line(base_line, company, rounding_method=rounding_method)
    #     self.with_context(
    #         compute_all_use_raw_base_lines=True,
    #     )._add_accounting_data_to_base_line_tax_details(base_line, company, include_caba_tags=include_caba_tags)
    #
    #     tax_details = base_line['tax_details']
    #     total_void = total_excluded = tax_details['raw_total_excluded_currency']
    #     total_included = tax_details['raw_total_included_currency']
    #
    #     # Convert to the 'old' compute_all api.
    #     taxes = []
    #     for tax_data in tax_details['taxes_data']:
    #         tax = tax_data['tax']
    #         for tax_rep_data in tax_data['tax_reps_data']:
    #             rep_line = tax_rep_data['tax_rep']
    #             taxes.append({
    #                 'id': tax.id,
    #                 'name': partner and tax.with_context(lang=partner.lang).name or tax.name,
    #                 'amount': tax_rep_data['tax_amount_currency'],
    #                 'base': tax_data['raw_base_amount_currency'],
    #                 'sequence': tax.sequence,
    #                 'account_id': tax_rep_data['account'].id,
    #                 'analytic': tax.analytic,
    #                 'use_in_tax_closing': rep_line.use_in_tax_closing,
    #                 'is_reverse_charge': tax_data['is_reverse_charge'],
    #                 'price_include': tax.price_include,
    #                 'tax_exigibility': tax.tax_exigibility,
    #                 'tax_repartition_line_id': rep_line.id,
    #                 'group': tax_data['group'],
    #                 'tag_ids': tax_rep_data['tax_tags'].ids,
    #                 'tax_ids': tax_rep_data['taxes'].ids,
    #             })
    #             if not rep_line.account_id:
    #                 total_void += tax_rep_data['tax_amount_currency']
    #
    #     if self._context.get('round_base', True):
    #         total_excluded = currency.round(total_excluded)
    #         total_included = currency.round(total_included)
    #
    #     return {
    #         'base_tags': base_line['tax_tag_ids'].ids,
    #         'taxes': taxes,
    #         'total_excluded': total_excluded,
    #         'total_included': total_included,
    #         'total_void': total_void,
    #     }
    #
    # @api.model
    # def _fix_tax_included_price(self, price, prod_taxes, line_taxes):
    #     """Subtract tax amount from price when corresponding "price included" taxes do not apply"""
    #     # FIXME get currency in param?
    #     prod_taxes = prod_taxes._origin
    #     line_taxes = line_taxes._origin
    #     incl_tax = prod_taxes.filtered(lambda tax: tax not in line_taxes and tax.price_include)
    #     if incl_tax:
    #         return incl_tax.custom_compute_all(price)['total_excluded']
    #     return price
    #
    # @api.model
    # def _fix_tax_included_price_company(self, price, prod_taxes, line_taxes, company_id):
    #     if company_id:
    #         # To keep the same behavior as in _compute_tax_id
    #         prod_taxes = prod_taxes.filtered(lambda tax: tax.company_id == company_id)
    #         line_taxes = line_taxes.filtered(lambda tax: tax.company_id == company_id)
    #     return self._fix_tax_included_price(price, prod_taxes, line_taxes)

    # @api.model
    # def _add_tax_details_in_base_line_custom(self, base_line, company, rounding_method=None):
    #     """ Perform the taxes computation for the base line and add it to the base line under
    #     the 'tax_details' key. Those values are rounded or not depending of the tax calculation method.
    #     If you need to compute monetary fields with that, you probably need to call
    #     '_round_base_lines_tax_details' after this method.
    #
    #     The added tax_details is a dictionary containing:
    #     raw_total_excluded_currency:    The total without tax expressed in foreign currency.
    #     raw_total_excluded:             The total without tax expressed in local currency.
    #     raw_total_included_currency:    The total tax included expressed in foreign currency.
    #     raw_total_included:             The total tax included expressed in local currency.
    #     taxes_data:                     A list of python dictionary containing the taxes_data returned by '_get_tax_details' but
    #                                     with the amounts expressed in both currencies:
    #         raw_tax_amount_currency         The tax amount expressed in foreign currency.
    #         raw_tax_amount                  The tax amount expressed in local currency.
    #         raw_base_amount_currency        The tax base amount expressed in foreign currency.
    #         raw_base_amount                 The tax base amount expressed in local currency.
    #
    #     :param base_line:       A base line generated by '_prepare_base_line_for_taxes_computation'.
    #     :param company:         The company owning the base line.
    #     :param rounding_method: The rounding method to be used. If not specified, it will be taken from the company.
    #     """
    #     rounding_method = rounding_method or company.tax_calculation_rounding_method
    #     price_unit_after_discount = base_line['price_unit'] * (1 - (base_line['discount'] / 100.0))
    #     taxes_computation = base_line['tax_ids']._get_tax_details(
    #         price_unit=price_unit_after_discount,
    #         quantity=base_line['quantity'],
    #         precision_rounding=base_line['currency_id'].rounding,
    #         rounding_method=rounding_method,
    #         product=base_line['product_id'],
    #         special_mode=base_line['special_mode'],
    #         manual_tax_amounts=base_line['manual_tax_amounts'],
    #         filter_tax_function=base_line['filter_tax_function'],
    #     )
    #     rate = base_line['rate']
    #     tax_details = base_line['tax_details'] = {
    #         'raw_total_excluded_currency': taxes_computation['total_excluded'],
    #         'raw_total_excluded': taxes_computation['total_excluded'] / rate if rate else 0.0,
    #         'raw_total_included_currency': taxes_computation['total_included'],
    #         'raw_total_included': taxes_computation['total_included'] / rate if rate else 0.0,
    #         'taxes_data': [],
    #     }
    #     if rounding_method == 'round_per_line':
    #         tax_details['raw_total_excluded'] = company.currency_id.round(tax_details['raw_total_excluded'])
    #         tax_details['raw_total_included'] = company.currency_id.round(tax_details['raw_total_included'])
    #     for tax_data in taxes_computation['taxes_data']:
    #         tax_amount = tax_data['tax_amount'] / rate if rate else 0.0
    #         base_amount = tax_data['base_amount'] / rate if rate else 0.0
    #         if rounding_method == 'round_per_line':
    #             tax_amount = company.currency_id.round(tax_amount)
    #             base_amount = company.currency_id.round(base_amount)
    #         tax_details['taxes_data'].append({
    #             **tax_data,
    #             'raw_tax_amount_currency': tax_data['tax_amount'],
    #             'raw_tax_amount': tax_amount,
    #             'raw_base_amount_currency': tax_data['base_amount'],
    #             'raw_base_amount': base_amount,
    #         })
    # #
    # # @api.model
    # # def _add_tax_details_in_base_lines_custom(self, base_lines, company):
    # #     """ Shortcut to call '_add_tax_details_in_base_line' on multiple base lines at once.
    # #
    # #     :param base_lines:  A list of base lines.
    # #     :param company:     The company owning the base lines.
    # #     """
    # #     for base_line in base_lines:
    # #         self._add_tax_details_in_base_line_custom(base_line, company)
    #
    # @api.model
    # def _round_base_lines_tax_details_custom(self, base_lines, company, tax_lines=None):
    #     """ Round the 'tax_details' added to base_lines with the '_add_accounting_data_to_base_line_tax_details'.
    #     This method performs all the rounding and take care of rounding issues that could appear when using the
    #     'round_globally' tax computation method, specially if some price included taxes are involved.
    #
    #     This method copies all float prefixed with 'raw_' in the tax_details to the corresponding float without 'raw_'.
    #     In almost all countries, the round globally should be the tax computation method.
    #     When there is an EDI, we need the raw amounts to be reported with more decimals (usually 6 to 8).
    #     So if you need to report the price excluded amount for a single line, you need to use
    #     'raw_total_excluded_currency' / 'raw_total_excluded' instead of 'total_excluded_currency' / 'total_excluded' because
    #     the latest are rounded. In short, rounding yourself the amounts is probably a mistake and you are probably adding some
    #     rounding issues in your code.
    #
    #     The rounding is made by aggregating the raw amounts per tax first.
    #     Then we round the total amount per tax, same for each tax amount in each base lines.
    #     Finally, we distribute the delta on each base lines.
    #     The delta is available in 'delta_total_excluded_currency' / 'delta_total_excluded' in each base line.
    #
    #     Let's take an example using round globally.
    #     Suppose two lines:
    #     l1: price_unit = 21.53, tax = 21% incl
    #     l2: price_unit = 21.53, tax = 21% incl
    #
    #     The raw_total_excluded is computed as 21.53 / 1.21 = 17.79338843
    #     The total_excluded is computed as round(17.79338843) = 17.79
    #     The total raw_base_amount for 21% incl is computed as 17.79338843 * 2 = 35.58677686
    #     The total base_amount for 21% incl is round(35.58677686) = 35.59
    #     The delta_base_amount is computed as 35.59 - 17.79 - 17.79 = 0.01 and will be added on l1.
    #
    #     For the tax amounts:
    #     The raw_tax_amount is computed as 21.53 / 1.21 * 0.21 = 3.73661157
    #     The tax_amount is computed as round(3.73661157) = 3.74
    #     The total raw_tax_amount for 21% incl is computed as 3.73661157 * 2 = 7.473223141
    #     The total tax_amount for 21% incl is computed as round(7.473223141) = 7.47
    #     The delta amount for 21% incl is computed as 7.47 - 3.74 - 3.74 = -0.01 and will be added to the corresponding
    #     tax_data in l1.
    #
    #     If l1 and l2 are invoice lines, the result will be:
    #     l1: price_unit = 21.53, tax = 21% incl, price_subtotal = 17.79, price_total = 21.53, balance = 17.80
    #     l2: price_unit = 21.53, tax = 21% incl, price_subtotal = 17.79, price_total = 21.53, balance = 17.79
    #     To compute the tax lines, we use the tax details in base_line['tax_details']['taxes_data'] that contain
    #     respectively 3.73 + 3.74 = 7.47.
    #     Since the untaxed amount of the invoice is computed based on the accounting balance:
    #     amount_untaxed = 17.80 + 17.79 = 35.59
    #     amount_tax = 7.47
    #     amount_total = 21.53 + 21.53 = 43.06
    #
    #     The amounts are globally correct because 35.59 * 0.21 = 7.4739 ~= 7.47.
    #
    #     :param base_lines:          A list of base lines generated using the '_prepare_base_line_for_taxes_computation' method.
    #     :param company:             The company owning the base lines.
    #     :param tax_lines:           A optional list of base lines generated using the '_prepare_tax_line_for_taxes_computation'
    #                                 method. If specified, the tax amounts will be computed based on those existing tax lines.
    #                                 It's used to keep the manual tax amounts set by the user.
    #     """
    #     total_per_tax = defaultdict(lambda: {
    #         'base_amount_currency': 0.0,
    #         'base_amount': 0.0,
    #         'raw_base_amount_currency': 0.0,
    #         'raw_base_amount': 0.0,
    #         'tax_amount_currency': 0.0,
    #         'tax_amount': 0.0,
    #         'raw_tax_amount_currency': 0.0,
    #         'raw_tax_amount': 0.0,
    #         'raw_total_amount_currency': 0.0,
    #         'raw_total_amount': 0.0,
    #         'base_lines': [],
    #     })
    #     total_per_base = defaultdict(lambda: {
    #         'base_amount_currency': 0.0,
    #         'base_amount': 0.0,
    #         'raw_base_amount_currency': 0.0,
    #         'raw_base_amount': 0.0,
    #         'tax_amount_currency': 0.0,
    #         'tax_amount': 0.0,
    #         'raw_total_amount_currency': 0.0,
    #         'raw_total_amount': 0.0,
    #         'base_lines': [],
    #     })
    #     map_total_per_tax_key_x_for_tax_line_key = defaultdict(set)
    #     country_code = company.account_fiscal_country_id.code
    #
    #     for base_line in base_lines:
    #         currency = base_line['currency_id']
    #         tax_details = base_line['tax_details']
    #         tax_details['total_excluded_currency'] = currency.round(tax_details['raw_total_excluded_currency'])
    #         tax_details['total_excluded'] = company.currency_id.round(tax_details['raw_total_excluded'])
    #         tax_details['delta_total_excluded_currency'] = 0.0
    #         tax_details['delta_total_excluded'] = 0.0
    #         tax_details['total_included_currency'] = currency.round(tax_details['raw_total_included_currency'])
    #         tax_details['total_included'] = company.currency_id.round(tax_details['raw_total_included'])
    #         taxes_data = tax_details['taxes_data']
    #
    #         # If there are taxes on it, account the amounts from taxes_data.
    #         for index, tax_data in enumerate(taxes_data):
    #             tax = tax_data['tax']
    #
    #             tax_data['tax_amount_currency'] = currency.round(tax_data['raw_tax_amount_currency'])
    #             tax_data['tax_amount'] = company.currency_id.round(tax_data['raw_tax_amount'])
    #             tax_data['base_amount_currency'] = currency.round(tax_data['raw_base_amount_currency'])
    #             tax_data['base_amount'] = company.currency_id.round(tax_data['raw_base_amount'])
    #
    #             tax_rounding_key = (tax, currency, base_line['is_refund'], tax_data['is_reverse_charge'])
    #             tax_line_key = (tax, currency, base_line['is_refund'])
    #             map_total_per_tax_key_x_for_tax_line_key[tax_line_key].add(tax_rounding_key)
    #             tax_amounts = total_per_tax[tax_rounding_key]
    #             tax_amounts['tax_amount_currency'] += tax_data['tax_amount_currency']
    #             tax_amounts['raw_tax_amount_currency'] += tax_data['raw_tax_amount_currency']
    #             tax_amounts['tax_amount'] += tax_data['tax_amount']
    #             tax_amounts['raw_tax_amount'] += tax_data['raw_tax_amount']
    #             tax_amounts['base_amount_currency'] += tax_data['base_amount_currency']
    #             tax_amounts['raw_base_amount_currency'] += tax_data['raw_base_amount_currency']
    #             tax_amounts['base_amount'] += tax_data['base_amount']
    #             tax_amounts['raw_base_amount'] += tax_data['raw_base_amount']
    #             tax_amounts['raw_total_amount_currency'] += tax_data['raw_base_amount_currency'] + tax_data[
    #                 'raw_tax_amount_currency']
    #             tax_amounts['raw_total_amount'] += tax_data['raw_base_amount'] + tax_data['raw_tax_amount']
    #             if not base_line['special_type']:
    #                 tax_amounts['base_lines'].append(base_line)
    #
    #             base_rounding_key = (currency, base_line['is_refund'])
    #             base_amounts = total_per_base[base_rounding_key]
    #             base_amounts['tax_amount_currency'] += tax_data['tax_amount_currency']
    #             base_amounts['tax_amount'] += tax_data['tax_amount']
    #             base_amounts['raw_total_amount_currency'] += tax_data['raw_tax_amount_currency']
    #             base_amounts['raw_total_amount'] += tax_data['raw_tax_amount']
    #             if index == 0:
    #                 base_amounts['base_amount_currency'] += tax_data['base_amount_currency']
    #                 base_amounts['raw_base_amount_currency'] += tax_data['raw_base_amount_currency']
    #                 base_amounts['base_amount'] += tax_data['base_amount']
    #                 base_amounts['raw_base_amount'] += tax_data['raw_base_amount']
    #                 base_amounts['raw_total_amount_currency'] += tax_data['raw_base_amount_currency']
    #                 base_amounts['raw_total_amount'] += tax_data['raw_base_amount']
    #                 if not base_line['special_type']:
    #                     base_amounts['base_lines'].append(base_line)
    #
    #         # If not, just account the base amounts.
    #         if not taxes_data:
    #             tax_rounding_key = (None, currency, base_line['is_refund'], False)
    #             tax_amounts = total_per_tax[tax_rounding_key]
    #             tax_amounts['base_amount_currency'] += tax_details['total_excluded_currency']
    #             tax_amounts['raw_base_amount_currency'] += tax_details['raw_total_excluded_currency']
    #             tax_amounts['base_amount'] += tax_details['total_excluded']
    #             tax_amounts['raw_base_amount'] += tax_details['raw_total_excluded']
    #             tax_amounts['raw_total_amount_currency'] += tax_details['raw_total_excluded_currency']
    #             tax_amounts['raw_total_amount'] += tax_details['raw_total_excluded']
    #             if not base_line['special_type']:
    #                 tax_amounts['base_lines'].append(base_line)
    #
    #             base_rounding_key = (currency, base_line['is_refund'])
    #             base_amounts = total_per_base[base_rounding_key]
    #             base_amounts['base_amount_currency'] += tax_details['total_excluded_currency']
    #             base_amounts['raw_base_amount_currency'] += tax_details['raw_total_excluded_currency']
    #             base_amounts['base_amount'] += tax_details['total_excluded']
    #             base_amounts['raw_base_amount'] += tax_details['raw_total_excluded']
    #             base_amounts['raw_total_amount_currency'] += tax_details['raw_total_excluded_currency']
    #             base_amounts['raw_total_amount'] += tax_details['raw_total_excluded']
    #             if not base_line['special_type']:
    #                 base_amounts['base_lines'].append(base_line)
    #
    #     # Round 'total_per_tax'.
    #     for (_tax, currency, _is_refund, _is_reverse_charge), tax_amounts in total_per_tax.items():
    #         tax_amounts['raw_tax_amount_currency'] = currency.round(tax_amounts['raw_tax_amount_currency'])
    #         tax_amounts['raw_tax_amount'] = company.currency_id.round(tax_amounts['raw_tax_amount'])
    #         tax_amounts['raw_base_amount_currency'] = currency.round(tax_amounts['raw_base_amount_currency'])
    #         tax_amounts['raw_base_amount'] = company.currency_id.round(tax_amounts['raw_base_amount'])
    #         tax_amounts['raw_total_amount_currency'] = currency.round(tax_amounts['raw_total_amount_currency'])
    #         tax_amounts['raw_total_amount'] = company.currency_id.round(tax_amounts['raw_total_amount'])
    #
    #     # Round 'total_per_base'.
    #     for (currency, _is_refund), base_amounts in total_per_base.items():
    #         base_amounts['raw_base_amount_currency'] = currency.round(base_amounts['raw_base_amount_currency'])
    #         base_amounts['raw_base_amount'] = company.currency_id.round(base_amounts['raw_base_amount'])
    #         base_amounts['raw_total_amount_currency'] = currency.round(base_amounts['raw_total_amount_currency'])
    #         base_amounts['raw_total_amount'] = company.currency_id.round(base_amounts['raw_total_amount'])
    #
    #     # If tax lines are provided, the totals will be aggregated according them.
    #     # Note: there is no managment of custom tax lines js-side.
    #     if tax_lines:
    #         # Aggregate the tax lines all together under the 'tax_line_key'.
    #         # Since the 'rounding_key' is not similar as 'tax_line_key' because we are not able to recover all
    #         # the key from an accounting tax lines, we have to map both and dispatch somehow the delta in term of
    #         # base and tax amounts.
    #         total_per_tax_line_key = defaultdict(lambda: {
    #             'tax_amount_currency': 0.0,
    #             'tax_amount': 0.0,
    #         })
    #         for tax_line in tax_lines:
    #             tax_rep = tax_line['tax_repartition_line_id']
    #             sign = tax_line['sign']
    #             tax = tax_rep.tax_id
    #             currency = tax_line['currency_id']
    #             tax_line_key = (tax, currency, tax_rep.document_type == 'refund')
    #             total_per_tax_line_key[tax_line_key]['tax_amount_currency'] += sign * tax_line['amount_currency']
    #             total_per_tax_line_key[tax_line_key]['tax_amount'] += sign * tax_line['balance']
    #
    #         # Reflect the difference to 'total_per_tax'.
    #         for tax_line_key, tax_line_amounts in total_per_tax_line_key.items():
    #             raw_tax_amount_currency = 0.0
    #             raw_tax_amount = 0.0
    #             rounding_keys = map_total_per_tax_key_x_for_tax_line_key[tax_line_key]
    #             if not rounding_keys:
    #                 continue
    #
    #             for tax_rounding_key in rounding_keys:
    #                 raw_tax_amount_currency += total_per_tax[tax_rounding_key]['raw_tax_amount_currency']
    #                 raw_tax_amount += total_per_tax[tax_rounding_key]['raw_tax_amount']
    #             delta_raw_tax_amount_currency = tax_line_amounts['tax_amount_currency'] - raw_tax_amount_currency
    #             delta_raw_tax_amount = tax_line_amounts['tax_amount'] - raw_tax_amount
    #             biggest_total_per_tax = max(
    #                 [
    #                     total_per_tax[rounding_key]
    #                     for rounding_key in rounding_keys
    #                 ],
    #                 key=lambda total_per_tax_amounts: total_per_tax_amounts['raw_tax_amount_currency'],
    #             )
    #             biggest_total_per_tax['raw_tax_amount_currency'] += delta_raw_tax_amount_currency
    #             biggest_total_per_tax['raw_tax_amount'] += delta_raw_tax_amount
    #
    #     # Dispatch the delta in term of tax amounts across the tax details when dealing with the 'round_globally' method.
    #     # Suppose 2 lines:
    #     # - quantity=12.12, price_unit=12.12, tax=23%
    #     # - quantity=12.12, price_unit=12.12, tax=23%
    #     # The tax of each line is computed as round(12.12 * 12.12 * 0.23) = 33.79
    #     # The expected tax amount of the whole document is round(12.12 * 12.12 * 0.23 * 2) = 67.57
    #     # The delta in term of tax amount is 67.57 - 33.79 - 33.79 = -0.01
    #     for (tax, currency, _is_refund, is_reverse_charge), tax_amounts in total_per_tax.items():
    #         if not tax_amounts['base_lines']:
    #             continue
    #
    #         tax_amounts['sorted_base_line_x_tax_data'] = [
    #             (
    #                 base_line,
    #                 next(
    #                     (
    #                         (index, tax_data)
    #                         for index, tax_data in enumerate(base_line['tax_details']['taxes_data'])
    #                         if tax_data['tax'] == tax and tax_data['is_reverse_charge'] == is_reverse_charge
    #                     ),
    #                     None,
    #                 )
    #             )
    #             for base_line in sorted(
    #                 tax_amounts['base_lines'],
    #                 key=lambda base_line: -base_line['tax_details']['total_included_currency'],
    #             )
    #         ]
    #         tax_amounts['total_included_currency'] = sum(
    #             abs(base_line['tax_details']['total_included_currency'])
    #             for base_line in tax_amounts['base_lines']
    #         )
    #         if not tax or not tax_amounts['total_included_currency']:
    #             continue
    #
    #         delta_tax_amount_currency = tax_amounts['raw_tax_amount_currency'] - tax_amounts['tax_amount_currency']
    #         delta_tax_amount = tax_amounts['raw_tax_amount'] - tax_amounts['tax_amount']
    #         for delta, delta_field, delta_currency in (
    #                 (delta_tax_amount_currency, 'tax_amount_currency', currency),
    #                 (delta_tax_amount, 'tax_amount', company.currency_id),
    #         ):
    #             if delta_currency.is_zero(delta):
    #                 continue
    #
    #             sign = -1 if delta < 0.0 else 1
    #             nb_of_errors = round(abs(delta / delta_currency.rounding))
    #             remaining_errors = nb_of_errors
    #             for base_line, index_tax_data in tax_amounts['sorted_base_line_x_tax_data']:
    #                 tax_details = base_line['tax_details']
    #                 if not remaining_errors or not index_tax_data:
    #                     break
    #
    #                 index, tax_data = index_tax_data
    #                 nb_of_amount_to_distribute = min(
    #                     math.ceil(abs(tax_details['total_included_currency'] * nb_of_errors / tax_amounts[
    #                         'total_included_currency'])),
    #                     remaining_errors,
    #                 )
    #                 remaining_errors -= nb_of_amount_to_distribute
    #                 amount_to_distribute = sign * nb_of_amount_to_distribute * delta_currency.rounding
    #                 tax_data[delta_field] += amount_to_distribute
    #                 tax_amounts[delta_field] += amount_to_distribute
    #
    #                 if index == 0:
    #                     base_rounding_key = (currency, base_line['is_refund'])
    #                     base_amounts = total_per_base[base_rounding_key]
    #                     base_amounts[delta_field] += amount_to_distribute
    #
    #     # Dispatch the delta of base amounts across the base lines.
    #     # Suppose 2 lines:
    #     # - quantity=12.12, price_unit=12.12, tax=23%
    #     # - quantity=12.12, price_unit=12.12, tax=23%
    #     # The base amount of each line is computed as round(12.12 * 12.12) = 146.89
    #     # The expected base amount of the whole document is round(12.12 * 12.12 * 2) = 293.79
    #     # The delta in term of base amount is 293.79 - 146.89 - 146.89 = 0.01
    #     for (tax, currency, _is_refund, _is_reverse_charge), tax_amounts in total_per_tax.items():
    #         if not tax_amounts.get('sorted_base_line_x_tax_data') or not tax_amounts.get('total_included_currency'):
    #             continue
    #
    #         if country_code == 'PT':
    #             delta_base_amount_currency = (
    #                     tax_amounts['raw_total_amount_currency']
    #                     - tax_amounts['base_amount_currency']
    #                     - tax_amounts['tax_amount_currency']
    #             )
    #             delta_base_amount = (
    #                     tax_amounts['raw_total_amount']
    #                     - tax_amounts['base_amount']
    #                     - tax_amounts['tax_amount']
    #             )
    #         else:
    #             delta_base_amount_currency = tax_amounts['raw_base_amount_currency'] - tax_amounts[
    #                 'base_amount_currency']
    #             delta_base_amount = tax_amounts['raw_base_amount'] - tax_amounts['base_amount']
    #
    #         for delta, delta_currency_indicator, delta_currency in (
    #                 (delta_base_amount_currency, '_currency', currency),
    #                 (delta_base_amount, '', company.currency_id),
    #         ):
    #             if delta_currency.is_zero(delta):
    #                 continue
    #
    #             sign = -1 if delta < 0.0 else 1
    #             nb_of_errors = round(abs(delta / delta_currency.rounding))
    #             remaining_errors = nb_of_errors
    #             for base_line, index_tax_data in tax_amounts['sorted_base_line_x_tax_data']:
    #                 tax_details = base_line['tax_details']
    #                 if not remaining_errors:
    #                     break
    #
    #                 nb_of_amount_to_distribute = min(
    #                     math.ceil(abs(tax_details['total_included_currency'] * nb_of_errors / tax_amounts[
    #                         'total_included_currency'])),
    #                     remaining_errors,
    #                 )
    #                 remaining_errors -= nb_of_amount_to_distribute
    #                 amount_to_distribute = sign * nb_of_amount_to_distribute * delta_currency.rounding
    #
    #                 if index_tax_data:
    #                     _index, tax_data = index_tax_data
    #                     tax_data[f'base_amount{delta_currency_indicator}'] += amount_to_distribute
    #                 else:
    #                     tax_details[f'delta_total_excluded{delta_currency_indicator}'] += amount_to_distribute
    #
    #                     base_rounding_key = (currency, base_line['is_refund'])
    #                     base_amounts = total_per_base[base_rounding_key]
    #                     base_amounts[f'base_amount{delta_currency_indicator}'] += amount_to_distribute
    #
    #     # Dispatch the delta of base amounts accross the base lines.
    #     # Suppose 2 lines:
    #     # - quantity=12.12, price_unit=12.12, tax=23%
    #     # - quantity=12.12, price_unit=12.12, tax=13%
    #     # The base amount of each line is computed as round(12.12 * 12.12) = 146.89
    #     # The expected base amount of the whole document is round(12.12 * 12.12 * 2) = 293.79
    #     # Currently, the base amount has already been rounded per tax. So the tax details for the whole document is currently:
    #     # 23%: base = 146.89, tax = 33.79
    #     # 13%: base = 146.89, tax = 19.1
    #     # However, for the whole document, there is a delta in term of base amount: 293.79 - 146.89 - 146.89 = 0.01
    #     # This delta won't be there in any base but still has to be accounted.
    #     for (currency, _is_refund), base_amounts in total_per_base.items():
    #         if not base_amounts['base_lines']:
    #             continue
    #
    #         base_line = max(
    #             base_amounts['base_lines'],
    #             key=lambda base_line: base_line['tax_details']['total_included_currency'],
    #         )
    #
    #         tax_details = base_line['tax_details']
    #         if country_code == 'PT':
    #             delta_base_amount_currency = (
    #                     base_amounts['raw_total_amount_currency']
    #                     - base_amounts['base_amount_currency']
    #                     - base_amounts['tax_amount_currency']
    #             )
    #             delta_base_amount = (
    #                     base_amounts['raw_total_amount']
    #                     - base_amounts['base_amount']
    #                     - base_amounts['tax_amount']
    #             )
    #         else:
    #             delta_base_amount_currency = base_amounts['raw_base_amount_currency'] - base_amounts[
    #                 'base_amount_currency']
    #             delta_base_amount = base_amounts['raw_base_amount'] - base_amounts['base_amount']
    #
    # @api.model
    # def _get_tax_totals_summary(self, base_lines, currency, company, cash_rounding=None):
    #     """ Compute the tax totals details for the business documents.
    #
    #     Don't forget to call '_add_tax_details_in_base_lines' and '_round_base_lines_tax_details' before calling this method.
    #
    #     :param base_lines:          A list of base lines generated using the '_prepare_base_line_for_taxes_computation' method.
    #     :param currency:            The tax totals is only available when all base lines share the same currency.
    #                                 Since the tax totals can be computed when there is no base line at all, a currency must be
    #                                 specified explicitely for that case.
    #     :param company:             The company owning the base lines.
    #     :param cash_rounding:       A optional account.cash.rounding object. When specified, the delta base amount added
    #                                 to perform the cash rounding is specified in the results.
    #     :return: A dictionary containing:
    #         currency_id:                            The id of the currency used.
    #         currency_pd:                            The currency rounding (to be used js-side by the widget).
    #         company_currency_id:                    The id of the company's currency used.
    #         company_currency_pd:                    The company's currency rounding (to be used js-side by the widget).
    #         has_tax_groups:                         Flag indicating if there is at least one involved tax group.
    #         same_tax_base:                          Flag indicating the base amount of all tax groups are the same and it's
    #                                                 redundant to display them.
    #         base_amount_currency:                   The untaxed amount expressed in foreign currency.
    #         base_amount:                            The untaxed amount expressed in local currency.
    #         tax_amount_currency:                    The tax amount expressed in foreign currency.
    #         tax_amount:                             The tax amount expressed in local currency.
    #         total_amount_currency:                  The total amount expressed in foreign currency.
    #         total_amount:                           The total amount expressed in local currency.
    #         cash_rounding_base_amount_currency:     The delta added by 'cash_rounding' expressed in foreign currency.
    #                                                 If there is no amount added, the key is not in the result.
    #         cash_rounding_base_amount:              The delta added by 'cash_rounding' expressed in local currency.
    #                                                 If there is no amount added, the key is not in the result.
    #         subtotals:                              A list of subtotal (like "Untaxed Amount"), each one being a python dictionary
    #                                                 containing:
    #             base_amount_currency:                   The base amount expressed in foreign currency.
    #             base_amount:                            The base amount expressed in local currency.
    #             tax_amount_currency:                    The tax amount expressed in foreign currency.
    #             tax_amount:                             The tax amount expressed in local currency.
    #             tax_groups:                             A list of python dictionary, one for each tax group, containing:
    #                 id:                                     The id of the account.tax.group.
    #                 group_name:                             The name of the group.
    #                 group_label:                            The short label of the group to be displayed on POS receipt.
    #                 involved_tax_ids:                       A list of the tax ids aggregated in this tax group.
    #                 base_amount_currency:                   The base amount expressed in foreign currency.
    #                 base_amount:                            The base amount expressed in local currency.
    #                 tax_amount_currency:                    The tax amount expressed in foreign currency.
    #                 tax_amount:                             The tax amount expressed in local currency.
    #                 display_base_amount_currency:           The base amount to display expressed in foreign currency.
    #                                                         The flat base amount and the amount to be displayed are sometimes different
    #                                                         (e.g. division/fixed taxes).
    #                 display_base_amount:                    The base amount to display expressed in local currency.
    #                                                         The flat base amount and the amount to be displayed are sometimes different
    #                                                         (e.g. division/fixed taxes).
    #     """
    #
    #     tax_totals_summary = {
    #         'currency_id': currency.id,
    #         'currency_pd': currency.rounding,
    #         'company_currency_id': company.currency_id.id,
    #         'company_currency_pd': company.currency_id.rounding,
    #         'has_tax_groups': False,
    #         'subtotals': [],
    #         'base_amount_currency': 0.0,
    #         'base_amount': 0.0,
    #         'tax_amount_currency': 0.0,
    #         'tax_amount': 0.0,
    #     }
    #
    #     # Global tax values.
    #     def global_grouping_function(base_line, tax_data):
    #         return True if tax_data else None
    #
    #     base_lines_aggregated_values = self._aggregate_base_lines_tax_details(base_lines, global_grouping_function)
    #     values_per_grouping_key = self._aggregate_base_lines_aggregated_values(base_lines_aggregated_values)
    #     for grouping_key, values in values_per_grouping_key.items():
    #         if grouping_key:
    #             tax_totals_summary['has_tax_groups'] = True
    #         tax_totals_summary['base_amount_currency'] += values['total_excluded_currency']
    #         tax_totals_summary['base_amount'] += values['total_excluded']
    #         tax_totals_summary['tax_amount_currency'] += values['tax_amount_currency']
    #         tax_totals_summary['tax_amount'] += values['tax_amount']
    #
    #     # Tax groups.
    #     untaxed_amount_subtotal_label = _("Untaxed Amount")
    #     subtotals = defaultdict(lambda: {
    #         'tax_groups': [],
    #         'tax_amount_currency': 0.0,
    #         'tax_amount': 0.0,
    #         'base_amount_currency': 0.0,
    #         'base_amount': 0.0,
    #     })
    #
    #     def tax_group_grouping_function(base_line, tax_data):
    #         return tax_data['tax'].tax_group_id if tax_data else None
    #
    #     base_lines_aggregated_values = self._aggregate_base_lines_tax_details(base_lines, tax_group_grouping_function)
    #     values_per_grouping_key = self._aggregate_base_lines_aggregated_values(base_lines_aggregated_values)
    #     sorted_total_per_tax_group = sorted(
    #         [values for grouping_key, values in values_per_grouping_key.items() if grouping_key],
    #         key=lambda values: (values['grouping_key'].sequence, values['grouping_key'].id),
    #     )
    #
    #     encountered_base_amounts = set()
    #     subtotals_order = {}
    #     for order, values in enumerate(sorted_total_per_tax_group):
    #         tax_group = values['grouping_key']
    #
    #         # Get all involved taxes in the tax group.
    #         involved_taxes = self.env['account.tax']
    #         for base_line, taxes_data in values['base_line_x_taxes_data']:
    #             for tax_data in taxes_data:
    #                 involved_taxes |= tax_data['tax']
    #
    #         # Compute the display base amounts.
    #         display_base_amount = values['base_amount']
    #         display_base_amount_currency = values['base_amount_currency']
    #         if set(involved_taxes.mapped('amount_type')) == {'fixed'}:
    #             display_base_amount = None
    #             display_base_amount_currency = None
    #         elif set(involved_taxes.mapped('amount_type')) == {'division'} and all(
    #                 involved_taxes.mapped('price_include')):
    #             for base_line, _taxes_data in values['base_line_x_taxes_data']:
    #                 for tax_data in base_line['tax_details']['taxes_data']:
    #                     if tax_data['tax'].amount_type == 'division':
    #                         display_base_amount_currency += tax_data['tax_amount_currency']
    #                         display_base_amount += tax_data['tax_amount']
    #
    #         if display_base_amount_currency is not None:
    #             encountered_base_amounts.add(float_repr(display_base_amount_currency, currency.decimal_places))
    #
    #         # Order of the subtotals.
    #         preceding_subtotal = tax_group.preceding_subtotal or untaxed_amount_subtotal_label
    #         if preceding_subtotal not in subtotals_order:
    #             subtotals_order[preceding_subtotal] = order
    #
    #         subtotals[preceding_subtotal]['tax_groups'].append({
    #             'id': tax_group.id,
    #             'involved_tax_ids': involved_taxes.ids,
    #             'tax_amount_currency': values['tax_amount_currency'],
    #             'tax_amount': values['tax_amount'],
    #             'base_amount_currency': values['base_amount_currency'],
    #             'base_amount': values['base_amount'],
    #             'display_base_amount_currency': display_base_amount_currency,
    #             'display_base_amount': display_base_amount,
    #             'group_name': tax_group.name,
    #             'group_label': tax_group.pos_receipt_label,
    #         })
    #
    #     # Subtotals.
    #     if not subtotals:
    #         subtotals[untaxed_amount_subtotal_label]
    #
    #     ordered_subtotals = sorted(subtotals.items(), key=lambda item: subtotals_order.get(item[0], 0))
    #     accumulated_tax_amount_currency = 0.0
    #     accumulated_tax_amount = 0.0
    #     for subtotal_label, subtotal in ordered_subtotals:
    #         subtotal['name'] = subtotal_label
    #         subtotal['base_amount_currency'] = tax_totals_summary[
    #                                                'base_amount_currency'] + accumulated_tax_amount_currency
    #         subtotal['base_amount'] = tax_totals_summary['base_amount'] + accumulated_tax_amount
    #         for tax_group in subtotal['tax_groups']:
    #             subtotal['tax_amount_currency'] += tax_group['tax_amount_currency']
    #             subtotal['tax_amount'] += tax_group['tax_amount']
    #             accumulated_tax_amount_currency += tax_group['tax_amount_currency']
    #             accumulated_tax_amount += tax_group['tax_amount']
    #         tax_totals_summary['subtotals'].append(subtotal)
    #
    #     # Cash rounding
    #     cash_rounding_lines = [base_line for base_line in base_lines if base_line['special_type'] == 'cash_rounding']
    #     if cash_rounding_lines:
    #         tax_totals_summary['cash_rounding_base_amount_currency'] = 0.0
    #         tax_totals_summary['cash_rounding_base_amount'] = 0.0
    #         for base_line in cash_rounding_lines:
    #             tax_details = base_line['tax_details']
    #             tax_totals_summary['cash_rounding_base_amount_currency'] += tax_details['total_excluded_currency']
    #             tax_totals_summary['cash_rounding_base_amount'] += tax_details['total_excluded']
    #     elif cash_rounding:
    #         strategy = cash_rounding.strategy
    #         cash_rounding_pd = cash_rounding.rounding
    #         cash_rounding_method = cash_rounding.rounding_method
    #         total_amount_currency = tax_totals_summary['base_amount_currency'] + tax_totals_summary[
    #             'tax_amount_currency']
    #         total_amount = tax_totals_summary['base_amount'] + tax_totals_summary['tax_amount']
    #         expected_total_amount_currency = float_round(
    #             total_amount_currency,
    #             precision_rounding=cash_rounding_pd,
    #             rounding_method=cash_rounding_method,
    #         )
    #         cash_rounding_base_amount_currency = expected_total_amount_currency - total_amount_currency
    #         rate = abs(total_amount_currency / total_amount) if total_amount else 0.0
    #         cash_rounding_base_amount = company.currency_id.round(
    #             cash_rounding_base_amount_currency / rate) if rate else 0.0
    #         if not currency.is_zero(cash_rounding_base_amount_currency):
    #             if strategy == 'add_invoice_line':
    #                 tax_totals_summary['cash_rounding_base_amount_currency'] = cash_rounding_base_amount_currency
    #                 tax_totals_summary['cash_rounding_base_amount'] = cash_rounding_base_amount
    #                 tax_totals_summary['base_amount_currency'] += cash_rounding_base_amount_currency
    #                 tax_totals_summary['base_amount'] += cash_rounding_base_amount
    #                 subtotals[untaxed_amount_subtotal_label][
    #                     'base_amount_currency'] += cash_rounding_base_amount_currency
    #                 subtotals[untaxed_amount_subtotal_label]['base_amount'] += cash_rounding_base_amount
    #             elif strategy == 'biggest_tax':
    #                 all_subtotal_tax_group = [
    #                     (subtotal, tax_group)
    #                     for subtotal in tax_totals_summary['subtotals']
    #                     for tax_group in subtotal['tax_groups']
    #                 ]
    #
    #                 if all_subtotal_tax_group:
    #                     max_subtotal, max_tax_group = max(
    #                         all_subtotal_tax_group,
    #                         key=lambda item: item[1]['tax_amount_currency'],
    #                     )
    #                     max_tax_group['tax_amount_currency'] += cash_rounding_base_amount_currency
    #                     max_tax_group['tax_amount'] += cash_rounding_base_amount
    #                     max_subtotal['tax_amount_currency'] += cash_rounding_base_amount_currency
    #                     max_subtotal['tax_amount'] += cash_rounding_base_amount
    #                     tax_totals_summary['tax_amount_currency'] += cash_rounding_base_amount_currency
    #                     tax_totals_summary['tax_amount'] += cash_rounding_base_amount
    #                 else:
    #                     # Failed to apply the cash rounding since there is no tax.
    #                     cash_rounding_base_amount_currency = 0.0
    #                     cash_rounding_base_amount = 0.0
    #
    #     # Subtract the cash rounding from the untaxed amounts.
    #     cash_rounding_base_amount_currency = tax_totals_summary.get('cash_rounding_base_amount_currency', 0.0)
    #     cash_rounding_base_amount = tax_totals_summary.get('cash_rounding_base_amount', 0.0)
    #     tax_totals_summary['base_amount_currency'] -= cash_rounding_base_amount_currency
    #     tax_totals_summary['base_amount'] -= cash_rounding_base_amount
    #     for subtotal in tax_totals_summary['subtotals']:
    #         subtotal['base_amount_currency'] -= cash_rounding_base_amount_currency
    #         subtotal['base_amount'] -= cash_rounding_base_amount
    #     encountered_base_amounts.add(float_repr(tax_totals_summary['base_amount_currency'], currency.decimal_places))
    #     tax_totals_summary['same_tax_base'] = len(encountered_base_amounts) == 1
    #
    #     # Total amount.
    #     tax_totals_summary['total_amount_currency'] = \
    #         tax_totals_summary['base_amount_currency'] + tax_totals_summary[
    #             'tax_amount_currency'] + cash_rounding_base_amount_currency
    #     tax_totals_summary['total_amount'] = \
    #         tax_totals_summary['base_amount'] + tax_totals_summary['tax_amount'] + cash_rounding_base_amount
    #
    #     return tax_totals_summary




class QuotationDiscountInherit(models.Model):
    _inherit=['sale.order']

    discount_choose = fields.Selection(
        selection=[('Custom', 'Custom Discount'), ('Original', 'Original Discount')],
        string="Discount Type:",
        default="Custom",
        store=True
    )
    discount_amount = fields.Float(string="Discount Amount:")


    # tax_totals = fields.Binary(compute='_compute_tax_totals_custom', exportable=False)
    # def process_discount
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

    # @api.onchange('discount_choose')
    # def onchange_discount_choose(self):
    #     self.order_line._compute_amount()
    #     self._compute_tax_totals()

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


    # @api.depends('order_line.price_subtotal', 'currency_id', 'company_id', 'payment_term_id')
    # def _compute_amounts(self):
    #     AccountTax = self.env['account.tax']
    #     for order in self:
    #         order_lines = order.order_line.filtered(lambda x: not x.display_type)
    #         base_lines = [line._prepare_base_line_for_taxes_computation_custom() for line in order_lines]
    #         base_lines += order._add_base_lines_for_early_payment_discount_custom()
    #         AccountTax._add_tax_details_in_base_lines_custom(base_lines, order.company_id)
    #         AccountTax._round_base_lines_tax_details_custom(base_lines, order.company_id)
    #         tax_totals = AccountTax._get_tax_totals_summary(
    #             base_lines=base_lines,
    #             currency=order.currency_id or order.company_id.currency_id,
    #             company=order.company_id,
    #         )
    #         order.amount_untaxed = tax_totals['base_amount_currency']
    #         order.amount_tax = tax_totals['tax_amount_currency']
    #         order.amount_total = tax_totals['total_amount_currency']
    #     print(tax_totals)

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

    # @api.onchange('price_unit', 'product_uom_qty', 'discount', 'custom_discount')
    # def process_discount_amount(self):
    #     for order in self:
    #         order.order_id.process_discount_amount()

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
        # for line in self:
        #     # Apply discount only if set
        #     price = line.price_unit * (1 - (line.custom_discount or 0.0) / 100)
        #     taxes = line.tax_id.compute_all(
        #         price,
        #         line.order_id.currency_id,
        #         line.product_uom_qty,
        #         product=line.product_id,
        #         partner=line.order_id.partner_shipping_id
        #     )
        #     # line.update({
        #     #     'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
        #     #     'price_total': taxes['total_included'],
        #     #     'price_subtotal': taxes['total_excluded'],
        #     # })
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
            # line.discount = line.custom_discount
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

# def _prepare_discount_product_values(self):
    #     self.ensure_one()
    #     return {
    #         'name': _('Discount'),
    #         'type': 'service',
    #         'invoice_policy': 'order',
    #         'list_price': 0.0,
    #         'company_id': self.company_id.id,
    #         'taxes_id': None,
    #     }
    #
    # def _prepare_discount_line_values(self, product, amount, taxes, description=None):
    #     self.ensure_one()
    #
    #     vals = {
    #         'order_id': self.sale_order_id.id,
    #         'product_id': product.id,
    #         'sequence': 999,
    #         'price_unit': -amount,
    #         'tax_id': [Command.set(taxes.ids)],
    #     }
    #     if description:
    #         # If not given, name will fallback on the standard SOL logic (cf. _compute_name)
    #         vals['name'] = description
    #
    #     return vals
    #
    # def _get_discount_product(self):
    #     """Return product.product used for discount line"""
    #     self.ensure_one()
    #     discount_product = self.company_id.sale_discount_product_id
    #     if not discount_product:
    #         if (
    #                 self.env['product.product'].has_access('create')
    #                 and self.company_id.has_access('write')
    #                 and self.company_id._filtered_access('write')
    #                 and self.company_id.check_field_access_rights('write', ['sale_discount_product_id'])
    #         ):
    #             self.company_id.sale_discount_product_id = self.env['product.product'].create(
    #                 self._prepare_discount_product_values()
    #             )
    #         else:
    #             raise ValidationError(_(
    #                 "There does not seem to be any discount product configured for this company yet."
    #                 " You can either use a per-line discount, or ask an administrator to grant the"
    #                 " discount the first time."
    #             ))
    #         discount_product = self.company_id.sale_discount_product_id
    #     return discount_product
    #
    # def _create_discount_lines(self):
    #     """Create SOline(s) according to wizard configuration"""
    #     self.ensure_one()
    #     discount_product = self._get_discount_product()
    #
    #     if self.discount_type == 'amount':
    #         if not self.sale_order_id.amount_total:
    #             return
    #         so_amount = self.sale_order_id.amount_total
    #         # Fixed taxes cannot be discounted, so they cannot be considered in the total amount
    #         # when computing the discount percentage.
    #         if any(tax.amount_type == 'fixed' for tax in
    #                self.sale_order_id.order_line.tax_id.flatten_taxes_hierarchy()):
    #             fixed_taxes_amount = 0
    #             for line in self.sale_order_id.order_line:
    #                 taxes = line.tax_id.flatten_taxes_hierarchy()
    #                 for tax in taxes.filtered(lambda tax: tax.amount_type == 'fixed'):
    #                     fixed_taxes_amount += tax.amount * line.product_uom_qty
    #             so_amount -= fixed_taxes_amount
    #         discount_percentage = self.discount_amount / so_amount
    #     else:  # so_discount
    #         discount_percentage = self.discount_percentage
    #     total_price_per_tax_groups = defaultdict(float)
    #     for line in self.sale_order_id.order_line:
    #         if not line.product_uom_qty or not line.price_unit:
    #             continue
    #         # Fixed taxes cannot be discounted.
    #         taxes = line.tax_id.flatten_taxes_hierarchy()
    #         fixed_taxes = taxes.filtered(lambda t: t.amount_type == 'fixed')
    #         taxes -= fixed_taxes
    #         total_price_per_tax_groups[taxes] += line.price_unit * (
    #                     1 - (line.discount or 0.0) / 100) * line.product_uom_qty
    #
    #     discount_dp = self.env['decimal.precision'].precision_get('Discount')
    #     context = {'lang': self.sale_order_id._get_lang()}  # noqa: F841
    #     if not total_price_per_tax_groups:
    #         # No valid lines on which the discount can be applied
    #         return
    #     if len(total_price_per_tax_groups) == 1:
    #         # No taxes, or all lines have the exact same taxes
    #         taxes = next(iter(total_price_per_tax_groups.keys()))
    #         subtotal = total_price_per_tax_groups[taxes]
    #         vals_list = [{
    #             **self._prepare_discount_line_values(
    #                 product=discount_product,
    #                 amount=subtotal * discount_percentage,
    #                 taxes=taxes,
    #                 description=_(
    #                     "Discount %(percent)s%%",
    #                     percent=float_repr(discount_percentage * 100, discount_dp),
    #                 ),
    #             ),
    #         }]
    #     else:
    #         vals_list = []
    #         for taxes, subtotal in total_price_per_tax_groups.items():
    #             discount_line_value = self._prepare_discount_line_values(
    #                 product=discount_product,
    #                 amount=subtotal * discount_percentage,
    #                 taxes=taxes,
    #                 description=_(
    #                     "Discount %(percent)s%%"
    #                     "- On products with the following taxes %(taxes)s",
    #                     percent=float_repr(discount_percentage * 100, discount_dp),
    #                     taxes=", ".join(taxes.mapped('name')),
    #                 ) if self.discount_type != 'amount' else _(
    #                     "Discount"
    #                     "- On products with the following taxes %(taxes)s",
    #                     taxes=", ".join(taxes.mapped('name')),
    #                 )
    #             )
    #             vals_list.append(discount_line_value)
    #     return self.env['sale.order.line'].create(vals_list)
    #
    # def action_apply_discount(self):
    #     self.ensure_one()
    #     self = self.with_company(self.company_id)
    #     if self.discount_type == 'sol_discount':
    #         self.sale_order_id.order_line.write({'discount': self.custom_discount * 100})
    #     else:
    #         self._create_discount_lines()
