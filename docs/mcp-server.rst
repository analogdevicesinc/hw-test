.. description::

   What the change-driven planning MCP server does, and how to drive it.

.. _hw-test-mcp-server:

Plan tests from a change
========================

``hw-test`` ships a companion MCP server. It turns a code change into an
honest, hardware-backed test plan: it reads a pull request or a local branch,
attributes the change to hardware subsystems, matches it against the existing
tests, and, when you ask, runs a matched test on a real board and reports what
happened. It never guesses a pass or fail; it validates what you give it and
reports only what a run observed.

You drive the server from an MCP client (for example Claude Code or another CLI
that speaks the protocol). The server exposes a small set of tools and a few
role prompts. The tools do the deterministic work; the prompts guide the
model through the steps.

What it does
------------

The server works in ordered phases. Each phase has its own tool, and each tool
crosses a JSON boundary so a client can call it directly.

Inspect
  Turn a change into a ``ChangeSet``: the merge-base, the head, the changed
  files, and the commits. ``inspect_pr`` reads a GitHub pull request;
  ``inspect_local`` reads a local branch or worktree against its base.

Classify
  Attribute the change to hardware subsystems. ``get_classification_evidence``
  returns the changed files, the tests that already match, and the closed list
  of subsystem choices. You pick a subsystem for each coherent part of the
  change and cite the files that justify it; ``submit_classification`` validates
  every entry against the subsystem list and the ``ChangeSet`` and rejects
  anything unbacked. The server never classifies for you.

Plan
  ``create_test_plan`` synthesizes a verdict-free plan from the validated
  classifications. The plan names the tests to reuse, states the coverage gap
  (``reuse``, ``parameterize``, or ``new``), and says what a hardware-less run
  would yield. It asserts no pass or fail.

Run
  ``run_base_vs_pr`` reserves a board, obtains the images, runs the matched
  test, and reports the outcome. ``mode="base-vs-pr"`` runs the test at the
  merge-base and at the head on the same board and reports the state delta.
  ``mode="head-only"`` runs just the head; use it when the base commit has no
  usable CI artifacts (for example when artifact retention has expired). The
  server always releases the board, even when a run fails.

Author
  When no test matches the change (coverage gap ``new`` or ``parameterize``),
  ``submit_test`` validates a test you author and stages it under
  ``tests/_staged/``. Validation parses the test, collects it with
  ``pytest --collect-only``, and checks its board tags against the live pool.
  A staged test is unrun and awaits human review; the server never promotes it
  or flashes a board with unreviewed code.

The tools
---------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Tool
     - What it does
   * - ``inspect_pr``
     - Inspect a GitHub pull request into a ``ChangeSet``.
   * - ``inspect_local``
     - Inspect a local branch or worktree into a ``ChangeSet`` against its base.
   * - ``get_classification_evidence``
     - Gather deterministic evidence: changed files, matched tests, the
       subsystem choices, and doc pointers.
   * - ``submit_classification``
     - Validate classifications against the subsystem list and the
       ``ChangeSet``.
   * - ``create_test_plan``
     - Synthesize an honest, verdict-free test plan.
   * - ``run_base_vs_pr``
     - Run a matched test on hardware and report the outcome.
   * - ``submit_test``
     - Validate an authored test and stage it for human review.

The prompts
-----------

The prompts drive focused roles. ``inspect-and-plan`` runs the whole
inspect-classify-plan pass. ``classify-changes`` drives the classifier alone.
``base-vs-pr-run`` drives the hardware runner. ``test-writer`` drives test
authoring. ``role-guide`` returns a one-paragraph guide for a named role.

How it stays honest
-------------------

The server reports what it can defend and nothing more. Every run ends with one
of a fixed set of result labels:

``validation-only``
  A run happened and reported its state. For a head-only run this is the PR-head
  state with no base to compare against.

``coverage-improvement``
  The test failed at the base and passed at the head.

``inconclusive``
  A run could not be read as a clear pass or fail.

``hardware-unavailable``
  No matching board was free to run the test.

``build-artifact-unavailable``
  No image could be obtained for the test (artifact miss and no build).

``test-design-requires-user-input``
  No reusable test exists; authoring is a separate step.

A matched test is required before any board is reserved. When there is no
reusable test, the server stops and reports that authoring is required rather
than running hardware.

A worked example
----------------

A watchdog change to U-Boot (`analogdevicesinc/u-boot#107`) touched the ADI
watchdog driver, its device tree, and several board defconfigs. Driving the
server through the phases:

* ``inspect_pr`` returned the ``ChangeSet``: fifteen files across four commits.
* Classifying the change attributed it to ``clock_reset_power``, ``board_dt``,
  and ``kconfig_build``, each citing the files that justified it.
* ``create_test_plan`` matched the existing ``adsp/u-boot`` test but reported
  that it only proves the board boots, not that the watchdog works. That gap
  called for a new, watchdog-specific test.
* An authored test went through ``submit_test`` and staged under
  ``tests/_staged/``. After review, it ran with ``run_base_vs_pr`` in
  ``head-only`` mode (the base commit's CI artifacts had expired).
* The run booted U-Boot on an ``sc598`` ``ezkit`` board and confirmed from
  ``dm tree`` that the watchdog device bound and probed. The result label was
  ``validation-only``: the head probes, with no base to compare against.

Connect a client
----------------

Point your MCP client at the server. It runs over stdio from a checkout of
``hw-test`` and needs ``LG_COORDINATOR`` in its environment so it can reach the
shared coordinator.

.. code:: json

   {
     "type": "stdio",
     "command": "/path/to/hw-test/.venv/bin/python3",
     "args": ["-m", "mcp_server.server"],
     "env": {
       "LG_COORDINATOR": "your-coordinator-host"
     }
   }

The server borrows the ``gh`` CLI's token to download CI artifacts, so make
sure ``gh`` is authenticated in the same environment, or set ``GITHUB_TOKEN``
explicitly.

Where to go next
----------------

* Run an existing test by hand: :ref:`run-a-test`.
* Write a new test for a supported platform: :ref:`write-a-test`.
* Read the design behind ``hw-test``: :ref:`How hw-test works <hw-test-concepts>`.
