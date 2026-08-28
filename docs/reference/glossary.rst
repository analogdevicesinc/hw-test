.. description::

   Mapping of hw-test terms to the Labgrid terms they correspond to.

.. _hw-test-glossary:

Glossary
========

``hw-test`` uses `Labgrid <https://labgrid.readthedocs.io/>`_ underneath to
share real hardware safely. This table maps the words used in the task guides to the Labgrid words you
may see in commands, configuration files, and the upstream Labgrid
documentation.

.. list-table::
   :header-rows: 1
   :widths: 22 22 56

   * - hw-test term
     - Labgrid term
     - Meaning
   * - Shared coordinator
     - Coordinator
     - The booking service that tracks all hardware and who has reserved each
       board. You connect to it by setting ``LG_COORDINATOR``.
   * - Hardware host
     - Exporter
     - The machine physically wired to a board: its serial console, power
       switch, debug probe, and other equipment.
   * - Board slot
     - Place
     - A reservable board in the shared pool. It carries capability tags (such
       as ``sc598`` and ``ezkit``) so tests can select it without knowing where
       it is or which serial number it has.
   * - Capability tag
     - Tag
     - A label on a board slot describing what it is (processor family, board
       model, fixture type). A test's ``needs`` list is matched against these.
   * - Driver
     - Driver
     - A single control on a board: power, serial console, GPIO, SSH, OpenOCD,
       or U-Boot. A test asks for a driver by its protocol.
   * - Place config
     - Place configuration
     - The configuration stored on the coordinator that maps a board slot's
       equipment to the drivers a test can use.

For full Labgrid syntax and options, see the
:external+labgrid:doc:`Labgrid documentation <index>`.
