.. description::

   How to prepare a hardware host for hw-test.

.. _set-up-a-hardware-host:

Set up a hardware host
======================

The hardware host is the machine connected to the board. It owns the USB serial
adapters, debug probes, power controllers, GPIO lines, and files staged for
operations. In Labgrid terminology, this host is called an *exporter*.
The coordinator tracks those resources, but the hardware host is the machine
that can physically access them.

If your team/organization already runs a :ref:`shared coordinator <hw-test-glossary>`; this
host joins it by setting ``LG_COORDINATOR`` in the exporter service below.
You do not set up a coordinator.

This page only covers hardware-host setup. To add a board after the host is
running, see :ref:`integrate-hardware`.

For the complete labgrid exporter syntax, use the upstream
:external+labgrid:ref:`exporter-configuration` reference.

Install Packages
++++++++++++++++

Install Python, serial tools, udev, ``iproute2``, and the tools needed by your
debug stack. Use the OpenOCD package from the system if it supports the board.
Build a custom OpenOCD only when the board support is not available in the
package.

.. tab-set::

   .. tab-item:: Ubuntu

      .. code:: bash

         sudo apt-get update
         sudo apt-get install -y \
           git python3 python3-venv python3-pip \
           firewalld microcom ser2net udev iproute2

      If OpenOCD must be built locally:

      .. code:: bash

         sudo apt-get install -y \
           autoconf automake libtool which pkg-config \
           libjim-dev gcc g++ make texinfo gdb-multiarch \
           libusb-1.0-0-dev

   .. tab-item:: Fedora

      .. code:: bash

         sudo dnf install -y \
           git python3 python3-pip \
           firewalld microcom ser2net systemd-udev iproute

      If OpenOCD must be built locally:

      .. code:: bash

         sudo dnf install -y \
           autoconf automake libtool which pkgconfig \
           jimtcl-devel gcc gcc-c++ make texinfo gdb \
           libusb1-devel

   .. tab-item:: openSUSE

      .. code:: bash

         sudo zypper install -y \
           git-core python3 python3-pip \
           firewalld microcom ser2net udev iproute2

      If OpenOCD must be built locally:

      .. code:: bash

         sudo zypper install -y \
           autoconf automake libtool which pkg-config \
           jimtcl-devel gcc gcc-c++ make texinfo gdb \
           libusb-1_0-devel

Users And Permissions
+++++++++++++++++++++

Use two Unix users:

``labgrid``
  Runs ``labgrid-exporter`` as a systemd user service.

``labgrid-client``
  Is used by clients and tests for SSH, ``scp``, ``rsync``, and remote helper
  commands.

Both users need access to serial ports, GPIO devices, and USB debug probes. The
``labgrid`` group is the exporter user's primary group; the client does not need
it.

.. code:: bash

   for group in users dialout uucp labgrid plugdev gpio; do
     getent group "$group" >/dev/null || sudo groupadd --system "$group"
   done

   sudo useradd --create-home --home-dir /home/labgrid \
     --shell /bin/bash --gid labgrid \
     --groups users,dialout,uucp,plugdev,gpio labgrid

   sudo useradd --create-home --user-group --shell /bin/bash \
     --groups users,dialout,uucp,plugdev,gpio labgrid-client

If the users already exist, update their groups:

.. code:: bash

   sudo usermod -aG users,dialout,uucp,plugdev,gpio labgrid
   sudo usermod -aG users,dialout,uucp,plugdev,gpio labgrid-client

.. code:: bash

   sudo loginctl terminate-user labgrid

This refreshes group membership for the ``labgrid`` user's next session.

Check real device permissions before debugging labgrid:

.. code:: bash

   readlink -f /dev/serial/by-id/<your-device>
   ls -l /dev/ttyUSB0
   id labgrid-client
   sudo -u labgrid-client test -r /dev/ttyUSB0 && echo client-can-read
   sudo -u labgrid-client test -w /dev/ttyUSB0 && echo client-can-write

For USB debug probes, install udev rules from OpenOCD or add a local rule for
the probe vendor and product ID:

.. code:: text

   ATTRS{idVendor}=="1234", ATTRS{idProduct}=="5678", MODE="660", GROUP="plugdev", TAG+="uaccess"

Then reload udev:

.. code:: bash

   sudo udevadm control --reload-rules
   sudo udevadm trigger

Directories
+++++++++++

Create the directories used by labgrid:

.. code:: bash

   sudo install -d -o labgrid -g labgrid -m 0755 /home/labgrid
   sudo install -d -o labgrid -g labgrid -m 0755 /home/labgrid/.config/labgrid
   sudo install -d -o labgrid -g labgrid -m 0755 /home/labgrid/.config/systemd/user
   sudo install -d -o labgrid -g labgrid -m 0755 /home/labgrid/.local/bin
   sudo install -d -o labgrid -g labgrid -m 0755 /home/labgrid/.local/share

Install Labgrid
+++++++++++++++

Install labgrid in a venv owned by the ``labgrid`` user:

.. code:: bash

   sudo -u labgrid git clone https://github.com/labgrid-project/labgrid.git \
     /home/labgrid/.local/share/labgrid
   sudo -u labgrid python3 -m venv /home/labgrid/.local/share/labgrid/venv
   sudo -u labgrid /home/labgrid/.local/share/labgrid/venv/bin/python \
     -m pip install --upgrade pip
   sudo -u labgrid /home/labgrid/.local/share/labgrid/venv/bin/python \
     -m pip install --upgrade /home/labgrid/.local/share/labgrid

Install labgrid from a checkout rather than a PyPI release when your exporter
needs a specific branch or a custom driver.

Verify the exporter command runs:

.. code:: bash

   sudo -u labgrid /home/labgrid/.local/share/labgrid/venv/bin/labgrid-exporter \
     --help >/dev/null

SSH And OPKSSH
++++++++++++++

``hw-test`` needs SSH to the hardware host because tests copy files and run
commands there. For local development, normal SSH keys are enough:

.. code:: bash

   ssh-copy-id labgrid-client@lab-exporter-01
   ssh labgrid-client@lab-exporter-01 true

The hardware host's SSH server must trust the identity used by your
organization. For GitHub Actions and OPKSSH requirements, see
:ref:`run-tests-in-ci`.

Exporter Service
++++++++++++++++

Create an empty exporter config file. The exporter stays effectively idle until
this file contains at least one real resource definition (see
:ref:`register-a-board`):

.. code:: bash

   sudo -u labgrid touch /home/labgrid/.config/labgrid/exporter.yml

The exporter must publish itself under the address that clients can reach. Use a
small wrapper that resolves the host's outbound IP address at start time and
passes it as ``--hostname``, so the exporter keeps working when the address
changes:

.. code:: bash

   sudo -u labgrid tee /home/labgrid/.local/bin/labgrid-exporter.sh >/dev/null <<'EOF'
   #!/bin/bash
   set -eu

   ip_=$(ip route get 8.8.8.8 | awk '{for (i = 1; i <= NF; i++) if ($i == "src") {print $(i + 1); exit}}')
   [ -n "$ip_" ] || { >&2 echo "error: could not get an ip"; exit 1; }

   exec "$HOME/.local/share/labgrid/venv/bin/labgrid-exporter" \
       --hostname "$ip_" -d "$HOME/.config/labgrid/exporter.yml"
   EOF
   sudo -u labgrid chmod 0755 /home/labgrid/.local/bin/labgrid-exporter.sh

Create the exporter user service. Replace the coordinator with the one your
team runs:

.. code:: bash

   sudo -u labgrid tee /home/labgrid/.config/systemd/user/labgrid-exporter.service >/dev/null <<'EOF'
   [Unit]
   Description=Labgrid Exporter
   After=network-online.target
   Wants=network-online.target
   StartLimitIntervalSec=0

   [Service]
   Environment="PYTHONUNBUFFERED=1"
   Environment="LG_COORDINATOR=labgrid-coordinator.example.com"
   ExecStart=%h/.local/bin/labgrid-exporter.sh
   Restart=always
   RestartSec=30

   [Install]
   WantedBy=default.target
   EOF

Enable the service:

.. code:: bash

   sudo loginctl enable-linger labgrid
   sudo systemctl --user --machine=labgrid@.host daemon-reload
   sudo systemctl --user --machine=labgrid@.host enable --now labgrid-exporter.service

Open the console proxy port range:

.. code:: bash

   sudo systemctl enable --now firewalld
   sudo firewall-cmd --permanent --add-port=30000-59999/tcp
   sudo firewall-cmd --reload

Check the service:

.. code:: bash

   sudo systemctl --user --machine=labgrid@.host status labgrid-exporter.service

If the service starts, the exporter host is ready. The next step is to register
a board in :ref:`register-a-board`.
