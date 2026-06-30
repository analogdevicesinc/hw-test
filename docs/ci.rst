.. description::

   Continuous deployment pipeline and instructions to set up a self-hosted
   hardware tests.

.. _ci:

Continuous integration
======================

Hardware tests continuous integration is focused on modularity and test selection.
In the next section, the different configuration options are explained.

.. note::

   Every repository that invokes ``labgrid`` tests must set the ``LG_COORDINATOR``
   secret and expose as an environment variable.

Workflow jobs
+++++++++++++

You can tune how the tests are spawned.

To run multiple tests in ``pytest`` under the same job, use:

.. code:: yaml

   jobs:
    hardware-tests:
      permissions:
        id-token: write
        contents: read
        actions: read
      uses: ./.github/workflows/run-test.yml
      with:
        set: >
          [
           {"name": "demo/basic"},
           {"name": "feature/new"},
           {"name": "something/test"}
          ]

Or spawn one job per test by using a matrix strategy:

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
      uses: ./.github/workflows/run-test.yml
      with:
        set: ${{ toJson(matrix.test) }}

Both methods are run in parallel, but the matrix completely isolates the tests
in different containers.

Workflow run
------------

Tests that use GitHub Artifacts need to know the ``workflow_run_id``.

If the **Build** and **Test** jobs **don't share** the same workflow id, you
:red:`must` add the ``workflow_run.url`` to the test set context.

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
      uses: ./.github/workflows/run-test.yml
      with:
        set: >
          {
            "name": "demo/basic",
            "workflow_run_url": "${{ github.event.workflow_run.url }}"
          }

If using workflow dispatch event, ensure ``workflow_run.url`` is propagated as an input:

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
      uses: ./.github/workflows/run-test.yml
      with:
        set: >
          {
            "name": "demo/basic",
            "workflow_run_url": "${{ inputs.workflow_run_url }}"
          }

You can also use :git+doctools:`action:workflow-run-to-context` to further enrich the context
with changed files and shas. See :git+hw-test:`.github/workflows/run-tests.yml` for a full
implementation.
