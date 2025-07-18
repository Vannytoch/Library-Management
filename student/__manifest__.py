# -*- coding: utf-8 -*-
{
    'name': "student",

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
    'depends': ['base', 'account'],

    # always loaded
    'data': [
        'data/res_partner_data.xml',
        'data/res.partner.title.csv',
        'security/ir.model.access.csv',
        'data/res.partner.csv',
        'views/student_views.xml',
        'views/school_views.xml',
        'views/hobby_views.xml',
        # 'views/templates.xml',
    ],
    # # only loaded in demonstration mode
    # 'demo': [
    #     'demo/demo.xml',
    # ],
    'insallable':True,
    'application': True,
}

