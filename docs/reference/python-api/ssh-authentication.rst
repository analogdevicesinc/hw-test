.. description::

   SSH access to exporter and target hosts.

SSH authentication
==================

Labgrid drives boards over SSH through the exporter hosts. In CI, OIDC
generates short-lived opkssh certificates to SSH to the Labgrid exporters.
Those methods are managed by ``LabgridClient``.

OPKSSH
------

.. automodule:: hw_tests.opkssh
   :no-members:

.. autoclass:: hw_tests.opkssh.OPKSSH

SSHConfig
---------

.. automodule:: hw_tests.ssh_config
   :no-members:

.. autoclass:: hw_tests.ssh_config.SSHConfig
