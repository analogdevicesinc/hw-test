.. description::

   Download build artifacts from GitHub and Cloudsmith.

Artifact storage
================

Firmware is built in other repositories and stored as GitHub workflow
artifacts, GitHub release assets, or Cloudsmith packages. These classes handle
authentication, lookup, and download.

They include a fallback to allow providing the artifacts directly, without
downloading from the storage buckets, allowing to use locally built artifacts.
For Cloudsmith, the fallback is when ``CLOUDSMITH_NAMESPACE`` is unset (no
token required for public repos), and GitHub, ``GITHUB_TOKEN`` (token
required).

GitHub
------

.. automodule:: hw_tests.github
   :no-members:

.. autoclass:: hw_tests.github.GitHub

Cloudsmith
----------

.. automodule:: hw_tests.cloudsmith
   :no-members:

.. autoclass:: hw_tests.cloudsmith.Cloudsmith
