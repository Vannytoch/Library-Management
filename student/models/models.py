import base64
import os.path
from email.policy import default

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import time
import re

# class partner(models.Model):
#     _inherit = "res.partner"
#
#     @api.model_create_multi
#     def create(self, vals):
#         for val in vals:
#             current_file_path = os.path.abspath(__file__)
#             current_dir = os.path.dirname(current_file_path)
#             module_dir = os.path.dirname(current_dir)
#             if "image_1920" in val:
#                 image_path= val.pop("image_1920")
#                 if os.path.isfile(module_dir+image_path):
#                     with open(module_dir+image_path, "rb") as img:
#                         val["image_1920"] = base64.b64encode(img.read()).decode("utf-8")
#         return super(partner, self).create(vals)

class SchoolStatus(models.Model):
    _name = 'school.status'
    _order= 'sequence'
    _description = 'Status'

    name = fields.Char(string="Status name")
    sequence = fields.Integer(string="Sequence", default=1)

class School(models.Model):
    _name = 'student.school'
    _description = 'School'

    status_id = fields.Many2one("school.status", "School Status")
    school_image = fields.Image("School Image", max_width=128, max_hieght=128)
    name = fields.Char(string="School name")
    invoice_id = fields.Many2one("account.move")
    invoice_user_id = fields.Many2one("res.users", related="invoice_id.invoice_user_id")
    invoice_date = fields.Date(related="invoice_id.invoice_date")
    student_ids = fields.One2many('student.student', 'school_id', string="Students")
    binary_fields = fields.Many2many("ir.attachment", string="Multi File Upload")
    binary_field = fields.Binary("Binary Fields")
    binary_file_name = fields.Char("Binary File Name", invisible="1")
    # currency_id = fields.Many2one("res.currency", "Currency")
    my_currency_id = fields.Many2one("res.currency", "My Currency")
    amount = fields.Monetary("Amount", currency_field="my_currency_id")
    ref_field_id = fields.Reference([
        ('student.student','Student'),
        ('student.school','School'),
        ('student.hobby','Hobby'),
        ('sale.order','Sale'),
        ('account.move','Invoice'),
        ('purchase.order','Purchase')
    ])

    def create(self, vals):
        print(self)
        print(vals)
        rtn = super(School, self).create(vals)
        print(rtn)
        return rtn
    def custom_method(self):
        print("custom method clicked!")
        print(self.amount)
        """
        abc = self.env['student.student'].search([])
        print(abc.read(fields=['name', 'school_id']))
        print(abc)
        """

        """
        # read_group()
        print(self)
        # self.read_group(
        #     domain,
        #     fields,
        #     group_by,
        #     offset=,
        #     limit=,
        #     order_by="",
        #     lazy = True, False
        # )
        student_group_by_school = self.env["student.student"].read_group(
            [],
            ["school_id", "gender"],
            ["school_id", "gender"]
        )
        for stud in student_group_by_school:
            print(stud)
        """

        # search_read()
        # self.search_read(
        #     domain,
        #     fields,
        #     offset=,
        #     limit=,
        #     order_by="",
        #     load=None
        # )
        # stud_obj = self.env['student.student']
        # # stud_list = stud_obj.search_read()
        # # print(stud_list)
        # stud_list = stud_obj.search_read([("school_id", ">", 1)],['id', 'name', 'school_id'])
        # print(stud_list)

        """
        # command spacial for
        # u can from odoo.fields import Command if u don't want just use fields.Command....
        # create => [0, 0, {val}], Command.create( {val} )
        # update => [1, id, {val}], Command.update(id, {val} )
        # delete => [2, id], Command.delete(id)
        # unlink => [3, id], Command.unlink(id)
        # link => [4, id], Command.link(id)
        # clear => [5], Command.clear()
        # set => [6,0,[ids]], Command.set([ids])

        ## partner.write({'category_id':[number Command or Text Command})
        # partner = self.env['res.partner'].browse(15)
        # 
        # print(partner, self)
        # partner.write({'category_id':[[5]]})
        """


        """
        # search(domain, limit, offset, order)
        # [condition, more condition]
        # #----------------------------------------
        # [('1','2','3')]
        # [
        #     ('field name', 'condition', 'field value'),
        #     ('field name', 'condition', 'field value'),
        #     ('field name', 'condition', 'field value')
        # ]
        # #----------------------------------------
        # records = self.search([('amount', '=', 500)])
        # self.print_table(records)
        #
        ##----------------------------------------
        # # when not input it will be None / False
        # records = self.search([('amount', '=?', False)])
        # self.print_table(records)
        ##----------------------------------------
        # # >, <, >=, <=, != allow too
        # records = self.search([('amount', '>', False)])
        # self.print_table(records)
        #----------------------------------------
        #
        # in <-> =  / not in <-> !=
        # ('a','b','c','d','e')
        # records = self.search([
        #     ('name', '=', 'ITC'),
        #     ('name', '=','Business')
        # ])
        # # Shortcut keyword
        # records = self.search([('name', 'in', ('ITC', 'Business'))])
        # self.print_table(records)
        # #----------------------------------------

        # # The LIKE operator matches case-sensitive string patterns,
        # # like / not like
        # records = self.search([('name', 'like', '%Business%')])
        # self.print_table(records)
        # #----------------------------------------


        # # =like ( '%text','text%', '%text%' )
        # #  %text like left
        # #  text% like right
        # #  %text% like left and right
        # records = self.search([('name', 'like', '%Business%')])
        # self.print_table(records)
        # #----------------------------------------


        # # whereas the ILIKE operator matches case-insensitive string patterns
        # # ilike ('%text','text%', '%text%') / =ilike
        # records = self.search([('name', 'ilike', '%Business%')])
        # self.print_table(records)
        # #----------------------------------------

        # # child_of
        # records = self.env["stock.location"].search([('location_id', 'child_of', 1)])
        # self.print_locations(records)
        # #----------------------------------------

        # # parent_of
        # records = self.env["stock.location"].search([('location_id', 'parent_of', 1)])
        # self.print_locations(records)
        # #----------------------------------------


        # # Join Query
        # # any / not any
        # # amount = 0 or name ilike itc
        # # use '!' for not , '|' for or, '&' for and, condition default is and condition
        # records = self.env["student.student"].search([
        #     '|','|',
        #     ('school_id.amount', '=',  0),
        #     ('school_id.name', 'ilike', 'itc'),
        #     ('school_id.my_currency_id', '=', False)
        # ])
        # # records = self.env["student.student"].search([('school_id', 'any', ['!', ('amount', '=', 0), ('name','ilike', 'itc')])])
        # self.print_table(records)
        # #----------------------------------------





        # print(self.search([]))
        #
        # # limit use for manage number of search lenght
        # print(self.search([], limit=5))
        #
        # # offset use for skipp fisrt data
        # print(self.search([], limit=5, offset=3))
        #
        # # order use for order by data
        # print(self.search([], order="id desc"))
        #
        # # env: use for call another table
        # print(self.env["student.student"].search([]))
        #
        # # print(self.search())
        # print(self.search([("name", "ilike", "ITC")]))
        """
        pass

    def print_table(self, records):
        print(f"Total record(s) found : {len(records)}")
        print(" ID              Name                 Student Fees                School")
        for record in records:
            print(f" {record.id}              {record.name}                 {record.student_fees}               {record.school_id.name}/{record.school_id.id}")
        print("")
        print("")
        print("")


    def print_locations(self, records):
        print(f"Total record(s) found : {len(records)}")
        print(" ID              Name                 Parent")
        for record in records:
            print(f" {record.id}              {record.name}                 {record.location_id.name} / {record.location_id.id}")
        print("")
        print("")
        print("")

    def duplicate_records(self):
        print(self)
        duplicate_record = self.copy()
        print(duplicate_record)

class Hobby(models.Model):
    _name = 'student.hobby'
    _description = 'Hobby'

    name = fields.Char(string="Hobby name")

class Student(models.Model):
    _name = 'student.student'
    _description = 'Student'

    hobby_list = fields.Many2many("student.hobby", "student_hobby_list_relation", "student_id", "hobby_id")
    name = fields.Char(string='Name', required=True)
    school_id = fields.Many2one('student.school', string="Select School", index=True)
    email = fields.Char(string='Email address', help='Enter a valid user email address', required=True)
    age = fields.Integer(string='Age')
    gender = fields.Selection(
        selection=[('male', 'Male'), ('female', 'Female')],
        string='Gender',
        required=True
    )
    joining_date = fields.Datetime(string="Join Date", default=fields.Datetime.now(), index=True)
    date_of_birth = fields.Date(string="Date of Birth", default=time.strftime("1980-01-01"))
    start_date = fields.Date(string="Start Date", default=time.strftime("%Y-01-01"))
    end_date = fields.Date(string="End Date", default=time.strftime("%Y-01-01"))
    test = fields.Char(string='Phone1')
    address = fields.Text(string='Address')
    school_data = fields.Json()
    status = fields.Selection([
        ("Draft", "Draft"),
        ("In Progress", "In progress"),
        ("Finish", "Finish")
    ], default="Draft" ,group_expand="_read_group_stage_ids"
    )
    student_image = fields.Image(string="Student Image")
    phone = fields.Char(string="Phone Number")
    student_fees = fields.Float(string="Student fees", default=3.2, help="Please enter student fees for current year.")
    discount_fees = fields.Float("Discount")
    final_fees = fields.Float("Final fees", compute="_compute_final_fees_cal", readonly=1)
    sequence = fields.Integer(string="Sequence", default=1)

    _sql_constraints = [
        ('unique_email', 'unique(email)', '⚠️ The email address has been used!')
    ]
    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return [ key for key, _ in  self._fields['status'].selection ]

    def abc_test(self):
        print(f"⚠️abc-------->{self}")

    def delete_records(self):
        print(self)
        school_id=self.env["student.school"].browse([3,55,66])
        for school in school_id:
            if not school.exists():
                raise UserError(f"Record in not available {school}")
                print("Instance or Recordset is not available ", school)
            else:
                print("Instance or recordset is available ", school)
        # print(school_id)
        # print(school_id.unlink)

    @api.onchange("student_fees", "discount_fees")
    def _compute_final_fees_cal(self):
        for record in self:
            record.final_fees = record.student_fees -record.discount_fees

    @staticmethod
    def _check_email_format(email):
        return bool(re.match(r"[^@]+@[^@]+\.[^@]+", email))

    @api.constrains('age')
    def _check_age_range(self):
        for record in self:
            if record.age is not None and (record.age < 18 or record.age > 60):
                raise ValidationError("Age must be between 18 and 60.")

    @api.constrains('email')
    def _validate_email(self):
        for rec in self:
            if rec.email and not self._check_email_format(rec.email):
                raise ValidationError(f"Invalid email format: {rec.email}")

    def json_data_store(self):
        self.school_data = {"name": self.name, "id": self.id, "g": self.gender}
