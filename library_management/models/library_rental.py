from odoo import models, fields, api
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from odoo.exceptions import UserError
import base64,openpyxl,io
from openpyxl.styles import Alignment

class RentalSystem(models.Model):
    _name = 'library.rental'
    _description = 'Rental System of Library'
    _rec_name = 'name'
    _order = 'name desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']  # Enables chatter + activity tracking

    name = fields.Char(
        string='Number',
        readonly=True,
        copy=False
    )
    member_id = fields.Many2one('library.member', string="Member", required=True, tracking=True)
    book_ids = fields.Many2many(
        'library.book',  # target model
        string="Book",
        tracking=True,
        required=True,
    )
    rental_date = fields.Date(string="Rental Date", default=fields.Date.context_today, required=True, tracking=True)
    due_date = fields.Date(string="Due Date", required=True, tracking=True)
    return_date = fields.Date(string="Return Date", tracking=True)
    rental_fee = fields.Monetary(
        string="Rental Fee",
        currency_field='currency_id',
        compute='_compute_rental_fee',
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

    available_book_ids = fields.Many2many('library.book', compute='_compute_available_books')
    is_visible_due = fields.Date(default=date.today(), required=True)

    def action_send_mail_rental(self):
        import logging
        _logger = logging.getLogger(__name__)
        template = self.env.ref('library_management.email_template_rental_overdue', raise_if_not_found=False)
        print("\n\n\nHello me\n\n\n\n")

        if not template:
            _logger.warning("Email template NOT found: library_management.email_template_rental_overdue")
        else:
            template.send_mail(self.id, force_send=True)
            if self.member_id.email:
                print("\n\n\n",self.member_id.email,"\n\n\n\n")

    @api.model
    def update_overdue_states(self):
        today = fields.Date.today()
        overdue_rentals = self.search([
            ('due_date', '<', today),
            ('return_date', '=', False),
            ('state', '!=', 'returned')
        ])
        for rental in overdue_rentals:
            rental.state = 'overdue'

    @api.depends('state', 'book_ids')
    def _compute_available_books(self):
        # Search all available books
        book_ids = self.book_ids.ids
        if book_ids:
            domain = ['|', ('id', 'in', book_ids), ('status', '=', 'available')]
        else:
            domain = [('status', '=', 'available')]

        available_book_ids = self.env['library.book'].search(domain)
        for member in self:
            member.available_book_ids = available_book_ids


    @api.depends('book_ids')
    def _compute_rental_fee(self):
        for record in self:
            record.rental_fee = sum(book.rental_fee for book in record.book_ids)

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
        print('\n\n\n\n',vals, '\n\n\n')
        self.check_due_date()
        res = super().create(vals)
        res.write({'name': f"R{res.id:06d}"})

        if 'book_ids' in vals and vals.get('member_id'):
            book_ids = []

            # Handle different command types in the many2many field
            for command in vals['book_ids']:
                if command[0] == 4:  # Link to existing record
                    book_ids.append(command[1])
                elif command[0] == 6:  # Replace all with new list of IDs
                    book_ids.extend(command[2])

            if book_ids and 'draft' not in vals['state']:
                books = self.env['library.book'].browse(book_ids)
                books.with_context(from_member_form=True).write({
                    'status': 'borrowed',
                    'member_id': vals['member_id']
                })

        return res

    @api.model
    def write(self, vals):

            # Keep track of added and removed book IDs
        added_books = set()
        removed_books = set()

        # Handle changes in book_ids
        if 'book_ids' in vals:
            for command in vals['book_ids']:
                if command[0] == 4:  # Add single book
                    added_books.add(command[1])
                elif command[0] == 3:  # Remove single book
                    removed_books.add(command[1])
                elif command[0] == 6:  # Replace all
                    new_ids = set(command[2])
                    old_ids = set(self.book_ids.ids)
                    added_books |= new_ids - old_ids
                    removed_books |= old_ids - new_ids
        if 'state' in vals and vals['state'] == 'confirmed' and 'book_ids' not in vals:
            books = self.env['library.book'].browse(self.book_ids.ids)
            for book in books:
                if book.status == 'borrowed':
                    raise UserError(f"The book '{book.title}' is not available (already borrowed).")
        # Apply status changes for added/removed books
        if added_books and 'state' in vals and 'draft' not in vals['state']:
            if 'state' in vals and vals['state'] == 'confirmed':
                books = self.env['library.book'].browse(added_books)
                for book in books:
                    if book.status == 'borrowed':
                        raise UserError(f"The book '{book.title}' is not available (already borrowed).")

            self.env['library.book'].browse(list(added_books)).with_context(from_member_form=True).write(
                {'status': 'borrowed'})
        if removed_books:
            self.env['library.book'].browse(list(removed_books)).with_context(from_member_form=True).write(
                {'status': 'available'})
        if 'state' in vals and 'draft' not in vals['state'] and 'book_ids' not in vals:
             self.env['library.book'].browse(self.book_ids.ids).with_context(from_member_form=True).write(
                {'status': 'borrowed'})
        # Call super to write vals
        result = super().write(vals)
        # Handle state change to 'returned'
        if 'state' in vals and vals['state'] in ['returned', 'draft']:
            for rec in self:
                rec.book_ids.with_context(from_member_form=True).write({'status': 'available'})


        return result

    def unlink(self):
        for rec in self:
            if rec.state not in ['returned']:
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
            rec.state = 'confirmed'

    def action_start(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError("Only Confirmed rentals can be started.")
            rec.state = 'active'

    def action_return(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Return Rentals',
            'res_model': 'library.rental.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_rental_ids': self.ids,
            }
        }


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

    def action_create_report(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generate Rental Report',
            'res_model': 'library.rental.report.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def generate_and_send_report(self):
        # Fetch records
        start_date = datetime.now() - relativedelta(months=1)
        end_date = datetime.now()
        domain = [
            ('rental_date', '>=', start_date),
            ('rental_date', '<=', end_date)
        ]
        rentals = self.env['library.rental'].sudo().search(domain)

        # Create XLSX
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Rental Report'
        ws.append(['Book', 'Due Date', 'Member', 'Rental Date', 'Rental Fee', 'Return Date', 'Status'])

        ws.column_dimensions['A'].width = 30  # Book Title
        ws.column_dimensions['B'].width = 30  # Date
        ws.column_dimensions['C'].width = 30  # Customer
        ws.column_dimensions['D'].width = 30  # Start
        ws.column_dimensions['E'].width = 30  # Fee
        ws.column_dimensions['F'].width = 30  # Return
        ws.column_dimensions['G'].width = 30  # State
        for r in rentals:
            book_title = ', '.join(r.book_ids.mapped('title'))
            ws.append([book_title, r.due_date, r.member_id.name, r.rental_date, r.rental_fee, r.return_date, r.state])

        for row in ws.iter_rows(min_row=2):
            row[0].alignment = Alignment(wrap_text=True)

        fp = io.BytesIO()
        wb.save(fp)
        fp.seek(0)
        xlsx_data = fp.read()

        # Send Email
        attachment = self.env['ir.attachment'].create({
            'name': f"rental_report_{datetime.now().strftime('%Y%m%d')}.xlsx",
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data),
            'res_model': 'library.rental',
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        # Replace with your real recipient email
        recipient_email = 'admin@example.com'
        mail_values = {
            'subject': 'Monthly Rental Report',
            'body_html': '<p>Please find attached the monthly rental report.</p>',
            'email_to': recipient_email,
            'attachment_ids': [(6, 0, [attachment.id])],
        }
        self.env['mail.mail'].sudo().create(mail_values).send()
