# Configuration file for the Sphinx documentation builder.

# -- Path setup --------------------------------------------------------------
import os
import sys

# add the project root (one level up) to sys.path
sys.path.insert(0, os.path.abspath('..'))

#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'test'
copyright = '2026, test'
author = 'test'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
  'sphinx.ext.autodoc',
  'sphinx.ext.viewcode',
  'sphinx.ext.napoleon',
  'sphinx.ext.mathjax',
  'nbsphinx',
  'myst_parser',
]

nbsphinx_execute = 'never'

templates_path = ['_templates']

master_doc = 'index'

source_suffix = {
    '.rst': 'restructuredtext',
}

exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store', '.*', '**/.ipynb_checkpoints/**']



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# -- Autodoc options ---------------------------------------------------------

# Show both the class docstring and the __init__ docstring
autoclass_content = 'both'

# If your docstrings use typing annotations, you may need this:
# autoclass_content = 'init'
# autodata_content = 'both'

# -- Napoleon settings (if you use Google or NumPy style docstrings) ---------

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
