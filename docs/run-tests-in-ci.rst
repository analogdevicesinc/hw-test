.. description::

   Run hw-test from a GitHub Actions workflow.

.. _run-tests-in-ci:

Run tests in CI
===============

Use ``hw-test`` from GitHub Actions when a build needs to be validated on a
real hardware. Your workflow selects a test; ``hw-test`` finds a compatible free
board, runs the test, and releases it when the job finishes.

If you are adding a test for the first time, write and run it locally first:
:ref:`write-a-test`.

.. note::

   Every repository that invokes hardware tests must set the ``LG_COORDINATOR``
   secret and expose it as an environment variable.

Run tests from a workflow
+++++++++++++++++++++++++

Call the reusable workflow with one test context:

.. code:: yaml

   jobs:
     hardware-test:
       permissions:
         id-token: write
         contents: read
         actions: read
       uses: analogdevicesinc/hw-test/.github/workflows/run-test.yml@main
       with:
         set: '{"name": "adsp/smoke"}'

Run more than one test
----------------------

To run multiple tests in one job, pass an array of test contexts:

.. code:: yaml

   jobs:
    hardware-tests:
      permissions:
        id-token: write
        contents: read
        actions: read
      uses: analogdevicesinc/hw-test/.github/workflows/run-test.yml@main
      with:
        set: >
          [
           {"name": "demo/basic"},
           {"name": "feature/new"},
           {"name": "something/test"}
          ]

To isolate tests in separate jobs, use a matrix:

.. code:: yaml

   jobs:
    hardware-tests:
      permissions:
        id-token: write
        contents: read
        actions: read
      strategy:
        fail-fast: false
        matrix:
          test:
          - name: "demo/basic"
          - name: "feature/new"
          - name: "something/test"
      uses: analogdevicesinc/hw-test/.github/workflows/run-test.yml@main
      with:
        set: ${{ toJson(matrix.test) }}

The matrix runs one test per job, so failures and logs are isolated.

Workflow run
------------

Tests that use GitHub Artifacts need the source workflow run URL.

If the **Build** and **Test** jobs do not share the same workflow run, add
``workflow_run_url`` to the test context.

For a workflow run triggered by the 'workflow_run' event, use:

.. code:: yaml

   on:
     workflow_run:
       workflows: ["Build"]
       types: [completed]

   permissions:
     actions: read
     contents: read
     id-token: write

   jobs:
    hardware-test:
      if: github.event.workflow_run.conclusion == 'success'
      permissions:
        id-token: write
        contents: read
        actions: read
      uses: analogdevicesinc/hw-test/.github/workflows/run-test.yml@main
      with:
        set: >
          {
            "name": "demo/basic",
            "workflow_run_url": "${{ github.event.workflow_run.url }}"
          }

If using a workflow-dispatch event, pass ``workflow_run_url`` as an input:

.. code:: yaml

   on:
    workflow_dispatch:
      inputs:
        workflow_run_url:
          description: "The api url of the workflow_run"
          required: true
          type: string

   permissions:
     actions: read
     contents: read
     id-token: write

   jobs:
    hardware-test:
      permissions:
        id-token: write
        contents: read
        actions: read
      uses: analogdevicesinc/hw-test/.github/workflows/run-test.yml@main
      with:
        set: >
          {
            "name": "demo/basic",
            "workflow_run_url": "${{ inputs.workflow_run_url }}"
          }

You can also use :git+doctools:`action:workflow-run-to-context` to further enrich the context
with changed files and shas. See :git+hw-test:`.github/workflows/run-tests.yml` for a full
implementation.
