"""Sphinx configuration."""
from datetime import datetime


project = "Miscellaneous Python scripts"
author = "Claudio Jolowicz"
copyright = f"{datetime.now().year}, {author}"
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx_click",
    "sphinxarg.ext",
]
autodoc_typehints = "description"
html_theme = "furo"
