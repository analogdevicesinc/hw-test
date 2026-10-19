.. description::

   Resolve firmware images by role.

Firmware Images
===============

Each build flavor names and packages its images differently. ``Images``
maps a role, such as ``spl`` or ``kernel``, to a file using the
``artifacts.toml`` of the test category, so one test runs against every
flavor. See :ref:`write-a-test`.

.. automodule:: hw_tests.images
   :no-members:

.. autoclass:: hw_tests.images.Images

.. autofunction:: hw_tests.images.find_one
