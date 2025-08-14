from odoo import models, fields, api
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError



class RentalSystem(models.Model):
    _name = 'library.rental'
    _description = 'Rental System of Library'
    _rec_name = 'name'
    _order = 'name desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Enables chatter + activity tracking

    name = fields.Char(string='Number', readonly=True, copy=False)
    member_id = fields.Many2one('library.member', string="Member", required=True, tracking=True)
    rental_date = fields.Date(string="Rental Date", default=fields.Date.context_today, required=True, tracking=True)
    due_date = fields.Date(string="Due Date", required=True, tracking=True)
    return_date = fields.Date(string="Return Date", tracking=True)
    available_book_ids = fields.Many2many('library.book', compute='_compute_available_books')
    is_visible_due = fields.Date(default=date.today(), required=True)
    total_amount = fields.Float(
        string='Total amount',
        compute='_compute_total_amount',
        currency_field = 'currency_id',
        tracking=True
    )
    total_rental = fields.Monetary(
        string="Total Rental",
        currency_field='currency_id',
        tracking=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('active', 'Active'),
        ('returned', 'Returned'),
        ('overdue', 'Overdue'),
    ], string="Status", default='draft', tracking=True,)
    rental_line_ids = fields.One2many(
        comodel_name='library.rental.line',
        inverse_name='rental_id',
        string='Rental Lines'
    )


    @api.depends('rental_line_ids.subtotal', 'rental_line_ids')
    def _compute_total_amount(self):
        for rec in self:
            if rec.rental_line_ids :
                total = 0.0
                for line in rec.rental_line_ids:
                    total+=line.subtotal
                rec.total_amount = total
            else:
                rec.total_amount = 0.00



    def action_send_mail_rental(self):

        template = self.env.ref('library_management.email_template_rental_overdue', raise_if_not_found=False)
        if not template:
            raise UserError("Email template NOT found: library_management.email_template_rental_overdue")
        else:
            template.send_mail(self.id, force_send=True)

    @api.model
    def update_overdue_states(self):
        today = fields.Date.today()
        overdue_rentals = self.search([
            ('due_date', '<', today),
            ('return_date', '=', False),
            ('state', '!=', 'returned')
        ])
        template = self.env.ref('library_management.email_template_rental_overdue', raise_if_not_found=False)
        for rental in overdue_rentals:
            rental.state = 'overdue'
            if template and rental.member_id.email:
                template.send_mail(rental.id, force_send=True)

    @api.depends('state',)
    def _compute_available_books(self):
        domain = [('status', '=', 'in_stock')]
        available_book_ids = self.env['library.book'].search(domain)
        for member in self:
            member.available_book_ids = available_book_ids

    # Automatically compute overdue status
    @api.onchange('due_date', 'return_date')
    def _check_overdue(self):
        for record in self:
            if record.state in ('active', 'confirmed') and record.due_date and not record.return_date:
                if fields.Date.context_today(record) > record.due_date:
                    record.state = 'overdue'

    @api.onchange('due_date', 'rental_date')
    def check_due_date(self):
        if self.rental_date and self.due_date:
            if self.rental_date > self.due_date:
                self.due_date = datetime.now() + timedelta(days=1)
                raise UserError('Due date must be after the rental date!')


    @api.model
    def create(self, vals):
        self.check_due_date()
        res = super().create(vals)
        res.write({'name': f"R{res.id:06d}"})
        return res

    def unlink(self):
        for rec in self:
            if rec.state not in ['returned', 'draft']:
                raise UserError("Cannot delete a record unless it's not returned yet.")
        return super(RentalSystem, self).unlink()

    # State transition methods
    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only Draft rentals can be confirmed.")
            if rec.due_date - rec.rental_date < timedelta(days=1):
                raise UserError("The rental period must be at least 1 full day.")
            if rec.return_date:
                raise UserError("Return date must be clear before confirm.")
            for line in rec.rental_line_ids:
                book = self.env['library.book'].browse(line.book_id.id)
                if book:
                    if line.qty > book.stock:
                        raise UserError(f"Not enough copies of '{book.title}' available in the library! Only {book.stock} left in stock.")
                book.write({'stock': book.stock - line.qty})
            rec.state = 'confirmed'

    def action_start(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError("Only Confirmed rentals can be started.")
            rec.state = 'active'

    def action_return(self):
        for rental in self:
            if rental.state not in ('active', 'overdue'):
                raise UserError("Only Active or Overdue rentals can be returned.")
            if rental.return_date and rental.return_date < rental.rental_date:
                raise UserError("Can't return, Check rental date and current date.")
            rental.state = 'returned'
            for line in rental.rental_line_ids:
                book = self.env['library.book'].browse(line.book_id.id)
                if book:
                    book.write({'stock': book.stock + line.qty})
            rental.return_date = fields.Date.today()



    def action_mark_overdue(self):
        for rec in self:
            if rec.state != 'active':
                raise UserError("Only Active rentals can be marked overdue.")
            rec.state = 'overdue'

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('confirmed', 'active', 'returned', 'overdue'):
                raise UserError("Can only reset from Confirmed, Active, Returned, or Overdue states.")
            rec.state = 'draft'
            rec.rental_date = date.today()
            rec.due_date = date.today() + relativedelta(months=1)
            rec.return_date = False
            for line in rec.rental_line_ids:
                book = self.env['library.book'].browse(line.book_id.id)
                if book:
                    book.write({'stock': book.stock + line.qty})

    def action_create_report(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate Rental Report',
            'res_model': 'library.rental.report.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
