======
rst2md
======

A utility and library to convert a reStructuredText document to Markdown.

This is tested against pinned documents (``tests/data/fetch.sh``)

.. note::

   Sphinx documents are partially supported: the roles and directives used by the CPython
   documentation are rendered as Sphinx displays them. Links with a URL in the source are kept.

Installation
------------

.. code-block::

    uv pip install rst2md

Usage
-----

This can be used as a library or from the command line.

As a library:

.. code-block:: python

    import pathlib
    from rst2md import convert_rst_to_md

    path = pathlib.Path('README.rst')
    with path.open('r') as f:
        data = f.read()

    md = convert_rst_to_md(path.name, data)

From the command line:

.. code-block:: bash

    python -m rst2md README.rst

Testing
-------

.. code-block:: bash

    uvx tox
