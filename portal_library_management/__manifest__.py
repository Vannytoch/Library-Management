# -*- coding: utf-8 -*-
{
    'name': "Library Management Portal",

    'summary': "Library Portal",

    'description': """
Long description of module's purpose
    """,

    'author': "My Company",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Portal',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['library_management', 'portal'],

    # always loaded
    'data': [
        'views/portal_template_view.xml',
    ],
}

