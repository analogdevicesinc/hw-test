.. description::

   How hw-test maps labgrid resources, places, and env files.

.. _labgrid-hardware-place:

Hardware Model
==============

This page is a short reference for how ``hw-test`` maps labgrid objects. It does
not describe the step-by-step board registration flow. For that, use
:ref:`register-a-board`.

For full labgrid syntax, use the upstream references:

* :external+labgrid:ref:`exporter-configuration`
* :external+labgrid:ref:`environment-configuration`
* :external+labgrid:doc:`configuration`

Labgrid Objects
+++++++++++++++

``coordinator``
  Tracks resources, Labgrid Places, tags, and locks.

``exporter``
  Runs beside the hardware and exposes resources to the coordinator.

``place``
  A lockable slot. In this repository it is usually one board, such as
  ``MUN-01-SC598_EZKIT-02``.

``envs/<place>.yaml``
  The client-side labgrid environment file used by ``hw-test``. It maps matched
  resources to drivers such as power, serial, SSH, GPIO, OpenOCD, and U-Boot.

``tests/<name>/config.toml``
  Describes the test context. The ``needs`` list selects compatible Labgrid
  Places by tag.

Resource Names
++++++++++++++

The resource names in ``exporter.yaml`` are the names used in env file
``bindings``. For example, if the exporter exposes a serial resource named
``console``, the env file binds it like this:

.. code:: yaml

   - SerialDriver:
       name: serial
       bindings:
         port: console

Use stable resource matches on the exporter. Avoid matching serial adapters only
by ``/dev/ttyUSB0``. Prefer unique serial IDs or stable physical USB paths.

Env File Shape
++++++++++++++

Each place needs a matching env file:

.. code:: text

   envs/<place>.yaml

The filename must match the place name. ``hw_tests.labgrid.LabgridClient``
selects a place, then loads that file.

Example:

.. code:: yaml

   targets:
     sample-target:
       resources:
         RemotePlace:
           name: "sample-place"
         NetworkService:
           username: "labgrid-client"
           address: "exporter.example.com"

       drivers:
         - SerialDriver:
             name: serial
             bindings:
               port: console

         - NetworkPowerDriver:
             name: power
             bindings:
               port: power

         - SSHDriver:
             name: ssh

         - OpenOCDDriver:
             name: openocd
             load_commands:
               - "source [find interface/adi-dbgagent.cfg]"
               - "source [find target/adspsc59x_a55.cfg]"
               - "source [find /tools/u-boot.tcl]"
               - "init"
               - "autoboot_elf"
               - "shutdown"

``RemotePlace`` imports resources matched to the place. ``NetworkService`` is
used for SSH operations on the exporter. Driver ``bindings`` must match resource
names from the place.

OpenOCD Scripts
+++++++++++++++

OpenOCD scripts installed on the exporter should be loaded from the exporter
side:

.. code:: yaml

   load_commands:
     - "source [find interface/adi-dbgagent.cfg]"
     - "source [find target/adspsc59x_a55.cfg]"
     - "source [find /tools/u-boot.tcl]"
     - "init"
     - "autoboot_elf"
     - "shutdown"

Do not put exporter-only OpenOCD scripts under the labgrid ``config:`` key.
That key is for files that live on the client and should be copied to the
exporter. Use ``source [find ...]`` for scripts already installed under the
exporter's OpenOCD script path.

Always include ``shutdown`` in one-shot OpenOCD command flows so the debugger is
released for the next run.
