from markupsafe import Markup
from odoo import models, fields, api
from datetime import date
from dateutil.relativedelta import relativedelta
import re

class LibraryMember(models.Model):
    _name = 'library.member'
    _description = 'Member come to our library.'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Name", required=True)
    dob = fields.Date(string="Date of Birth")
    gender = fields.Selection(string="Gender", selection=[('male', 'Male'), ('female', 'Female')], default="male")
    image_1920 = fields.Binary(string="Photo")
    email = fields.Char(string="Email", required=True)
    address = fields.Text(string="Address")
    membership_id = fields.Char(
        string="Membership ID",
        compute='_compute_membership_id',
        store=True,
        readonly=True,
    )
    membership_type = fields.Selection([
    ('student', 'Student'),
    ('teacher', 'Teacher'),
    ('public', 'Public'),
    ('child', 'Child'),
    ('vip', 'VIP')], string="Membership Type", default="public")
    expiry_date = fields.Date(
        string="Expiry Date",
        default=lambda self: date.today() + relativedelta(years=1)
    )
    contact = fields.Char(string="Emergency Contact")
    institution = fields.Char(string="Institution")


    @api.depends('expiry_date')
    def _compute_membership_id(self):
        for record in self:
            if not record.membership_id:
                year_str = str(date.today().year)
                prefix = 'M' + year_str

                # Find last membership_id for this year (ignore current record)
                last_member = self.search(
                    [('membership_id', 'ilike', prefix), ('id', '!=', record.id)],
                    order='membership_id desc',
                    limit=1
                )
                if last_member:
                    last_id = last_member.membership_id
                    last_number = int(last_id[len(prefix):])
                    new_number = last_number + 1
                else:
                    new_number = 1

                record.membership_id = f"{prefix}{new_number:05d}"

    @api.onchange('email')
    def onchange_email(self):
        if self.email:
            # Simple email format validation using regex
            pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
            if not re.match(pattern, self.email):
                return {
                    'warning': {
                        'title': "Invalid Email Format",
                        'message': "Please enter a valid email address (e.g., user@example.com)."
                    }
                }

    @api.model
    def create(self, vals_list):
        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        for vals in vals_list:
            if vals.get('membership_id', 'New') == 'New':
                year_str = str(date.today().year)
                prefix = 'M' + year_str
                last_member = self.search([('membership_id', 'ilike', prefix)], order='membership_id desc', limit=1)
                if last_member:
                    last_number = int(last_member.membership_id[len(prefix):])
                    new_number = last_number + 1
                else:
                    new_number = 1
                vals['membership_id'] = f"{prefix}{new_number:05d}"

        records = super(LibraryMember, self).create(vals_list)
        return records