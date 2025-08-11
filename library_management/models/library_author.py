from odoo import models, fields, api
from datetime import datetime
import re

class Author(models.Model):
    _name = 'library.author'
    _description = 'Author write book in this library'

    name = fields.Char(string="Author Name")
    age = fields.Integer(string="Age")
    email = fields.Char(string="Email")
    dob = fields.Date(string="Date of Birth")
    pob = fields.Text(string="Place of Birth")

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

    # @api.depends('dob')
    # def _compute_age(self):
    #     for res in self:
    #         if res.dob:
    #             today = datetime.today().date()
    #             dob = res.dob
    #             res.age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    #         else:
    #             res.age = 0