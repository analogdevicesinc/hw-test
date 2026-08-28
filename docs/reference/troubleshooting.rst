.. description::

   What to check when a hardware test or setup step fails.

.. _hw-test-troubleshooting:

Troubleshooting
===============

A local test run fails
-----------------------

Check these first:

* ``LG_COORDINATOR`` points to the right shared hardware service.
* ``labgrid-client places`` shows a :ref:`board slot <hw-test-glossary>` for the
  platform.
* The test's ``needs`` list matches the board slot's capability tags.
* ``labgrid-client -p <board-slot> show`` displays a valid coordinator-side
  config with the expected resources and drivers.
* The hardware host is reachable over SSH.

A driver is missing
--------------------

The board's available drivers come from its coordinator-side place config. If
``get_driver(...)`` fails, ask whoever maintains the fixture to add the driver;
the mapping is explained in :ref:`labgrid-hardware-place`.

Artifacts will not download
---------------------------

If you see ``Neither 'workflow_run_url' in context or 'GITHUB_REPOSITORY' in
environment``, the run has no artifact source. Either pass ``workflow_run_url``
with a ``GITHUB_TOKEN``, or place local files at the printed
``_artifacts/<test-name>/0/`` path. See :ref:`run-a-test`.

The exporter service will not start
-----------------------------------

On the hardware host:

* Check status: ``sudo systemctl --user --machine=labgrid@.host status labgrid-exporter.service``.
* Confirm device permissions for the ``labgrid-client`` user:

  .. code:: bash

     ls -l /dev/ttyUSB0
     sudo -u labgrid-client test -r /dev/ttyUSB0 && echo client-can-read
     sudo -u labgrid-client test -w /dev/ttyUSB0 && echo client-can-write

* Confirm ``/var/cache/labgrid`` exists and is writable by the ``labgrid`` group.

A client cannot see resources from an exporter that did not start. Fix the
service first. See :ref:`set-up-a-hardware-host`.
