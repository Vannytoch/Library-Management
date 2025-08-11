# -*- coding: utf-8 -*-
{
    'name': "Library_Management",

    'summary': "Short (1 phrase/line) summary of the module's purpose",

    'description': """
Long description of module's purpose
    """,

    'author': "My Company",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'web', 'mail', 'portal'],

    # always loaded
    'data': [
        'data/cron.xml',
        'data/mail_template.xml',
        'security/ir.model.access.csv',

        'views/portal_template_view.xml',
        'views/portal_book.xml',
        'views/library_dashboard.xml',

        'views/book_views.xml',
        'views/author_views.xml',
        'views/member_views.xml',
        'views/rental_views.xml',
        'reports/book_report.xml',
        'reports/report_rental_wizard.xml',
        'reports/rental_report.xml',
        'reports/rental_report_templates.xml',
    ],

}

