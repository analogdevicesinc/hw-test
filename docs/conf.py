
# -- Project information -----------------------------------------------------

repository = 'hw-test'
project = 'Hardware Test'
copyright = '2026, Analog Devices, Inc.'
author = 'Analog Devices, Inc.'
version = '0.1'

language = 'en'

# -- General configuration ---------------------------------------------------

extensions = [
    'adi_doctools',
    'sphinx.ext.intersphinx',
]

needs_extensions = {
    'adi_doctools': '0.3'
}

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
source_suffix = '.rst'

#  -- Options for PDF output --------------------------------------------------

latex_show_pagerefs = True

latex_show_urls = 'footnote'

# -- External docs configuration ----------------------------------------------

intersphinx_mapping = {
    'labgrid': ('https://labgrid.readthedocs.io/en/latest', None),
}

# -- Options for HTML output --------------------------------------------------

html_theme = 'harmonic'

html_theme_options = {}
