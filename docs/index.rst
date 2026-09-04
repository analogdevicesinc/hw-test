Hardware tests
==============

``hw-test`` runs repeatable tests against real Analog Devices hardware. It works
from a developer shell or from CI, and it shares a pool of boards safely between
teams. You ask for a board by its capabilities; ``hw-test`` finds a compatible
free board, runs your test, and releases it.

What do you want to do?
-----------------------

* Run a test on a board that is already set up -> :ref:`run-a-test`.
* Write a new test for a supported platform -> :ref:`write-a-test`.
* Plan tests with the MCP server -> :ref:`hw-test-mcp-server`.
* Add my board or fixture to the shared pool -> :ref:`integrate-hardware`.
* Run hardware tests from CI -> :ref:`run-tests-in-ci`.
* Set up a new hardware host for my team -> :ref:`set-up-a-hardware-host`.

New here?
------------------------------------

``hw-test`` is built on `Labgrid <https://labgrid.readthedocs.io/>`_, but you do
not need to learn it to run or write a test. If you want the see the design first,
read :ref:`How hw-test works <hw-test-concepts>`. When you meet an unfamiliar
term, the :ref:`glossary <hw-test-glossary>` can help.

Reference and troubleshooting
-----------------------------

The :ref:`reference section <hw-test-reference>` covers the hardware model, the
client API, the glossary, and :ref:`troubleshooting <hw-test-troubleshooting>`.
The complete :external+labgrid:doc:`Labgrid documentation <index>` is useful
when you need options beyond the workflows here.

.. toctree-preview::
   :hidden:

   concepts
   run-a-test
   write-a-test
   mcp-server
   integrate-hardware
   register-a-board
   run-tests-in-ci
   set-up-a-hardware-host
   reference/index
