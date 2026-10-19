.. description::

   Python API reference.

API reference
=============

The ``hw_tests`` package holds the code shared by all tests: reserving a
board, building the test context, fetching firmware, and setting up SSH.
Tests import it instead of calling labgrid, GitHub, or Cloudsmith directly.

.. toctree-preview::
   :maxdepth: 1

   labgrid-client
   test-executor
   artifact-storage
   firmware-images
   ssh-authentication
   logging
