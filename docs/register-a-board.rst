.. description::

   Detailed commands for registering a board or fixture with hw-test.

.. _register-a-board:

Register a board
================

This is the command-level companion to :ref:`integrate-hardware`. Start there
for the overall workflow and the choices to make before editing
configuration. Use this page when you are ready to add the board's
resources, :ref:`board slot <hw-test-glossary>`, and coordinator-side place
config.

The hardware host should already be prepared. If it is not, start with
:ref:`set-up-a-hardware-host`.

The flow is:

1. identify stable hardware IDs on the hardware host,
2. add resources to ``exporter.yaml``,
3. restart and check the exporter,
4. create a board slot,
5. add the place config to the coordinator,
6. verify the board from the CLI,
7. run the matching pytest test.

Identify connected hardware
+++++++++++++++++++++++++++

Run these commands on the hardware host while the board is connected:

.. code:: bash

   ls -l /dev/serial/by-id
   lsusb
   udevadm info --query=property --name=/dev/ttyUSB0
   labgrid-suggest

Prefer stable matches:

* use ``ID_SERIAL`` when the adapter has a unique serial number,
* use ``ID_PATH`` when the physical USB port is the stable part of the setup,
* use ``ID_VENDOR_ID`` and ``ID_MODEL_ID`` for USB probes.

Publish hardware resources
++++++++++++++++++++++++++

Edit the exporter config:

.. code:: text

   /home/labgrid/.config/labgrid/exporter.yaml

Example:

.. code:: yaml

   MUN-01-SC598_EZKIT-02:
     console:
       cls: USBSerialPort
       match:
         "@ID_SERIAL": "Example_UART_1234"
     debugger:
       cls: USBDebugger
       match:
         ID_PATH: "pci-0000:00:14.0-usb-0:12.2.1"
     power:
       cls: NetworkPowerPort
       model: example
       host: "http://power-controller.example"
       index: 1

   shared-ftdi:
     pin-d3:
       cls: NetworkSysfsGPIO
       host: "lab-exporter-01"
       index: 123

Restart and check the exporter:

.. code:: bash

   sudo systemctl --user --machine=labgrid@.host restart labgrid-exporter.service
   sudo systemctl --user --machine=labgrid@.host status labgrid-exporter.service

If the service fails, fix that first. A client cannot see resources from an
exporter that did not start.

Create a board slot
+++++++++++++++++++

Run these commands from a client with ``LG_COORDINATOR`` set:

.. code:: bash

   export LG_COORDINATOR=<coordinator-hostname>
   labgrid-client -p MUN-01-SC598_EZKIT-02 create
   labgrid-client -p MUN-01-SC598_EZKIT-02 add-match '*/MUN-01-SC598_EZKIT-02/*'
   labgrid-client -p MUN-01-SC598_EZKIT-02 add-match '*/shared-ftdi/*'
   labgrid-client -p MUN-01-SC598_EZKIT-02 set-tags family=adsp board=sc598 kind=ezkit
   labgrid-client -p MUN-01-SC598_EZKIT-02 show

The tags must match the ``needs`` list of the tests that should run on this
board.

Add the coordinator-side place config
+++++++++++++++++++++++++++++++++++++

The place config is stored by the coordinator, so every client and CI job gets
the same resource and driver definitions. The place must be idle while editing
it. Run:

.. code:: bash

   labgrid-client -p MUN-01-SC598_EZKIT-02 edit

Paste the target body below. Do not wrap it in ``targets:`` and do not add a
``RemotePlace`` resource; the selected place is already the remote target:

.. code:: yaml

   resources:
     - NetworkService:
         username: "labgrid-client"
         address: "10.44.3.61"

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

     - FTDIGPIODriver:
         name: spi_boot
         bindings:
           gpio: pin-d3

     - OpenOCDDriver:
         name: openocd
         load_commands:
           - "source [find interface/adi-dbgagent.cfg]"
           - "source [find target/adspsc59x_a55.cfg]"
           - "source [find /tools/u-boot.tcl]"
           - "init"
           - "autoboot_elf"
           - "shutdown"

     - UBootDriver:
         name: uboot
         prompt: "=> "
         bindings:
           console: serial

Verify the board from the CLI
+++++++++++++++++++++++++++++

Acquire the place:

.. code:: bash

   labgrid-client -p MUN-01-SC598_EZKIT-02 acquire

Then test one operation at a time:

.. code:: bash

   labgrid-client -p MUN-01-SC598_EZKIT-02 io low pin-d3
   labgrid-client -p MUN-01-SC598_EZKIT-02 power cycle
   labgrid-client -p MUN-01-SC598_EZKIT-02 scp images/u-boot-spl :u-boot-spl
   labgrid-client -p MUN-01-SC598_EZKIT-02 scp images/u-boot :u-boot
   labgrid-client -p MUN-01-SC598_EZKIT-02 bootstrap dummy
   labgrid-client -p MUN-01-SC598_EZKIT-02 console

Release when done:

.. code:: bash

   labgrid-client -p MUN-01-SC598_EZKIT-02 release

Run a test
++++++++++

After the CLI flow works, run one pytest test:

.. code:: bash

   set='{"name": "adsp/u-boot"}' pytest -vvs

Start with one test and one place. Do not begin with ``pytest tests`` while
bringing up a new setup.
