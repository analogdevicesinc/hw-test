.. description::

   Run hw-test from a GitHub Actions workflow.

.. _run-tests-in-ci:

Run tests in CI
===============

Call ``analogdevicesinc/hw-test/.github/workflows/run-test.yml@main`` from a
GitHub Actions job with one JSON test context. The called workflow checks out
``hw-test``, installs the selected test's requirements, and runs pytest against
a compatible board. If the test needs build artifacts, run it after the jobs
that publish them.

Prepare the calling repository
------------------------------

Set a repository secret named ``LG_COORDINATOR`` to the coordinator address
and pass it with ``secrets: inherit``. Give the job ``contents: read`` for
checkout and ``id-token: write`` for hardware-host SSH authentication. Tests
that download build artifacts also need ``actions: read``. If a test uses
``Images``, the uploaded artifact must match its
``tests/<category>/artifacts.toml`` entry. The runner must be able to reach the
coordinator and hardware host.

Start with one test
-------------------

Add this job under ``jobs`` in the calling workflow. Replace
``<category>/<test-name>`` with a test directory under ``tests/``:

.. code:: yaml

   jobs:
     hardware-test:
       uses: analogdevicesinc/hw-test/.github/workflows/run-test.yml@main
       with:
         set: '{"name":"<category>/<test-name>"}'
       secrets: inherit
       permissions:
         actions: read
         contents: read
         id-token: write

The test's ``config.toml`` supplies its default board tags through ``needs``.
To choose another compatible board type, add ``"needs":["board-tag","feature-tag"]``
to ``set``. These tags also narrow artifact selection when a test uses images.
If a ``build`` job uploads the artifacts in the same workflow, add
``needs: [build]`` to ``hardware-test``. Without ``workflow_run_url``, the
test reads artifacts from the current run.

Run several tests
-----------------

The reusable ``run-test.yml`` workflow accepts **one JSON object per call**.
Use a matrix for separate results and logs:

.. code:: yaml

   jobs:
     hardware-test:
       strategy:
         fail-fast: false
         matrix:
           test:
             - name: "<category>/<first-test>"
             - name: "<category>/<second-test>"
       uses: analogdevicesinc/hw-test/.github/workflows/run-test.yml@main
       with:
         set: ${{ toJson(matrix.test) }}
       secrets: inherit
       permissions:
         actions: read
         contents: read
         id-token: write

You can also put a ``needs`` list in each matrix object to choose different
board variants. If the tests need artifacts, make the matrix job depend on
the build jobs that upload them. See the
`br2-external <https://github.com/analogdevicesinc/br2-external/blob/main/.github/workflows/top-level.yml>`_,
`U-Boot <https://github.com/analogdevicesinc/u-boot/blob/adi-u-boot-2025.10.y/.github/workflows/top-level.yml>`_,
and `Linux <https://github.com/analogdevicesinc/linux/blob/adsp-6.18.31-y/.github/workflows/top-level.yml>`_
workflows for examples with different build jobs, test names, and board tags.

Run against a different workflow run
------------------------------------

If build and test do not share a run, pass the build run's **API URL**:

.. code:: yaml

   on:
     workflow_run:
       workflows: ["Build"]
       types: [completed]

   jobs:
     hardware-test:
       if: github.event.workflow_run.conclusion == 'success'
       uses: analogdevicesinc/hw-test/.github/workflows/run-test.yml@main
       with:
         set: >-
           {"name":"<category>/<test-name>","workflow_run_url":"${{ github.event.workflow_run.url }}"}
       secrets: inherit
       permissions:
         actions: read
         contents: read
         id-token: write

The URL must look like
``https://api.github.com/repos/OWNER/REPO/actions/runs/RUN_ID``. A browser
URL under ``github.com/OWNER/REPO/actions/runs/`` is not the input format.

Select tests from changed files
-------------------------------

``hw-test`` also has a manually dispatched
:git+hw-test:`.github/workflows/run-tests.yml`. It accepts
``workflow_run_url``, calls ``doctools/workflow-run-to-context``, and runs
``hw_tests.collect`` to build a matrix of matching tests. This path is useful
when you want test selection driven by ``[[repository]]`` rules in each
``config.toml`` instead of an explicit matrix. A rule matches when the source
repository name, branch ref, and at least one changed-file glob all match.
The resulting context includes the source SHA and workflow run URL.

Trigger this workflow in the ``hw-test`` repository with the build run's API
URL. The direct reusable workflow above runs the test you name regardless of
those path rules.

If a job fails
--------------

Check that the called job received ``LG_COORDINATOR`` and the required
permissions, that any expected artifact has the right name and file layout,
and that ``needs`` matches a registered board. A caller from a fork may not
receive repository secrets. See :ref:`hw-test-troubleshooting` for hardware
connectivity checks.
