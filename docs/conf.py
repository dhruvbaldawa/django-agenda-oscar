# -- Django workaround
import django
import os
import sys

sys.path.append(os.path.dirname(__file__))
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"
django.setup()

# -- Project information -----------------------------------------------------

project = "Django Agenda"
copyright = "2019, Alan Trick"
author = "Alan Trick"

extensions = ["sphinx.ext.doctest", "sphinx.ext.autodoc"]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

source_suffix = ".rst"

master_doc = "index"

language = None

exclude_patterns = ["_build", "api/modules.rst", "api/django_agenda.migrations"]

pygments_style = "sphinx"


# -- Options for HTML output -------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

# -- Options for LaTeX output ------------------------------------------------

latex_elements = {}

latex_documents = [
    (master_doc, "DjangoAgenda.tex",
     "Django Agenda Documentation", "Alan Trick", "manual")
]


# -- Options for manual page output ------------------------------------------

man_pages = [(master_doc, "django_agenda", "Django Agenda Documentation", [author], 1)]


# -- Options for Texinfo output ----------------------------------------------

texinfo_documents = [
    (
        master_doc,
        "DjangoAgenda",
        "Django Agenda Documentation",
        author,
        "DjangoAgenda",
        "One line description of project.",
        "Miscellaneous",
    )
]
