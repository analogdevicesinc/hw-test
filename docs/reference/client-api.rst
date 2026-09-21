.. description::

   Python API and test context reference for hw-test.

.. _labgrid-client-repo:

Python API reference
====================

A hardware test is a pytest function in ``tests/<category>/<test-name>/test.py``
that accepts ``context``. A test that uses build artifacts usually needs three
objects: ``LabgridClient`` to reserve a board, ``GitHub`` to read a build run,
and ``Images`` to find files in its artifacts. The rest of this page covers the
helpers used by the test runner and by tests with special needs. For a first
test, follow :ref:`write-a-test`; for a local run, see :ref:`run-a-test`.

A complete small test looks like this:

.. code:: python

   from hw_tests.github import GitHub
   from hw_tests.images import Images
   from hw_tests.labgrid import LabgridClient

   def test_boot_image(context):
       image = Images(context, GitHub(context)).get("kernel")
       assert image.is_file()
       with LabgridClient(context).acquire() as target:
           ssh = target.get_driver("SSHDriver")
           ssh.put(str(image), "Image")

Context and pytest selection
----------------------------

The ``context`` dictionary starts with ``{"name": <test directory>}``. Pytest
loads the adjacent ``config.toml``, converts named TOML lists such as
``[[repository]]`` into dictionaries keyed by ``name``, then merges an override
from the ``set`` environment variable. Nested dictionaries merge; a scalar or
list in the override replaces the default. A string ``needs`` value becomes a
one-item list. Tests may add their own keys.

.. list-table:: Context keys understood by hw-test
   :header-rows: 1

   * - Key
     - Use
   * - ``name``
     - Test directory relative to ``tests/``, such as ``adsp/u-boot``.
   * - ``needs``
     - Required place tags. Every token must match a tag key or value. A list
       of lists in ``config.toml`` creates one pytest case per board variant.
   * - ``labgrid_target``
     - Exact place name, when you need a particular board. It still must match
       ``needs``.
   * - ``labgrid_coordinator``
     - Coordinator address; takes precedence over ``LG_COORDINATOR``.
   * - ``workflow_run_url``
     - Build run's API URL, such as
       ``https://api.github.com/repos/OWNER/REPO/actions/runs/123``. It takes
       precedence over ``GITHUB_REPOSITORY`` and ``GITHUB_RUN_ID`` for artifact
       downloads.
   * - ``flavor``
     - Section to use in ``artifacts.toml``. If absent, ``Images`` uses the
       repository name from the build run.
   * - ``repository``
     - Mapping of repository names to per-repository values such as ``ref``.
       ``[[repository]]`` entries in ``config.toml`` become this mapping.

For example, this override replaces the default board tags and selects one
place:

.. code:: bash

   set='{"name":"adsp/u-boot","needs":["sc598","ezlite"],"labgrid_target":"MUN-01-SC598_EZLITE-01"}' pytest -vvv

``set`` accepts one JSON object or an array of objects. Pytest selects the
named tests and gives each one its matching override. The reusable
``run-test.yml`` workflow accepts **one object per job**, so use a matrix for
several tests in CI; see :ref:`run-tests-in-ci`.

The context functions live in ``hw_tests.context``. Test code normally receives
the pytest fixture rather than calling them itself.

.. list-table:: ``hw_tests.context``
   :header-rows: 1

   * - Call
     - Returns or does
   * - ``parse_set_env()``
     - Parses ``set`` as JSON and returns a list of override dictionaries;
       returns ``[]`` when unset. Invalid JSON raises ``JSONDecodeError``.
   * - ``test_name(test_dir)``
     - Returns the directory's path relative to ``tests/`` as a string.
   * - ``build_context(test_dir, overrides)``
     - Reads ``config.toml``, merges the first override whose ``name`` matches,
       and returns the context dictionary. Missing config is allowed.
   * - ``deep_merge(base, override)``
     - Returns a new dictionary with recursive dictionary merging; other
       values, including lists, are replaced.
   * - ``reformat_named_lists(value)``
     - Recursively turns a list of dictionaries that all have ``name`` into a
       dictionary keyed by those names. Other lists stay lists.

Board access: ``hw_tests.labgrid``
----------------------------------

``LabgridClient(context)`` requires ``needs`` and a coordinator address from
``context["labgrid_coordinator"]`` or ``LG_COORDINATOR``. Construction finds a
matching configured place and stores its name in ``client.place`` and its
address in ``client.coordinator``. If several free places match, it chooses
the first by name. If all matches are busy, it checks every 30 seconds for up
to an hour. No matching place, a missing coordinator, or an expired wait raises
``AssertionError``.

``client.acquire()`` is a context manager that yields a Labgrid ``Target``.
It reserves the place, configures SSH, and releases the place on exit, even if
the test raises. Use the target's Labgrid drivers inside the ``with`` block:

.. code:: python

   from hw_tests.labgrid import LabgridClient

   def test_smoke(context):
       with LabgridClient(context).acquire() as target:
           power = target.get_driver("PowerProtocol")
           ssh = target.get_driver("SSHDriver")
           power.cycle()
           ssh.run_check("true")

Use ``target.get_driver(..., activate=False)`` if the driver must be activated
later with ``target.activate(driver)``. Drivers and ``Target`` belong to
Labgrid; consult its :external+labgrid:doc:`documentation <index>` for their
full API. ``hw-test`` configures SSH authentication automatically when it
acquires a place. In Actions this requires ``id-token: write``; locally, the
hardware host must accept your SSH key.

``exporter_http_server(ssh, files)`` is a second context manager. ``ssh`` is
the acquired target's ``SSHDriver``; ``files`` maps relative HTTP paths to
local file paths. It copies the files to the hardware host, starts a temporary
HTTP server there, and yields its port as a string. It stops the server and
removes the files on exit. Absolute paths, ``..``, and duplicate destinations
raise ``ValueError``. See :git+hw-test:`tests/adsp/initramfs-boot/test.py` for
a boot test that uses it.

.. code:: python

   from hw_tests.labgrid import exporter_http_server

   with exporter_http_server(ssh, {"boot/Image": image}) as port:
       # The board can fetch boot/Image from the hardware host on this port.
       print(port)

GitHub artifacts: ``hw_tests.github``
-------------------------------------

``GitHub(context)`` reads ``GITHUB_TOKEN``. It identifies the run from
``context["workflow_run_url"]`` or, if absent, ``GITHUB_REPOSITORY`` and
``GITHUB_RUN_ID``. It does not require a token at construction time. Its
``owner_repository`` property exposes the selected ``OWNER/REPO`` string.

.. list-table:: ``GitHub`` calls
   :header-rows: 1

   * - Call
     - Returns or does
   * - ``list_artifacts(owner_repository=None, run_id=None, source=None)``
     - Returns GitHub API artifact dictionaries from the run, excluding expired
       artifacts. Returns ``[]`` when repository, run ID, or token is missing.
       ``source`` switches to release assets; see below.
   * - ``download(name, owner_repository=None, run_id=None, path=None, source=None)``
     - Downloads one named artifact, extracts ZIP or tar archives, and returns
       the destination directory as a ``Path``. ``path`` sets that directory
       for run artifacts; ``owner_repository`` and ``run_id`` override the
       instance's run. A missing name raises ``StopIteration`` at lookup;
       HTTP failures raise ``requests.HTTPError``.
   * - ``GitHub.in_actions()``
     - Returns whether ``GITHUB_ACTIONS`` is ``true``.
   * - ``GitHub.mask(value)``
     - Registers a value for log redaction and adds a GitHub Actions mask when
       running in Actions.
   * - ``GitHub.get_id_token()``
     - Requests and returns an Actions OIDC token. Requires the Actions token
       request variables, provided by a job with ``id-token: write``.

Without repository, run ID, or token, ``download`` returns a local fallback
path such as ``_artifacts/adsp/u-boot/0/`` instead of fetching. Put files there
for an offline run; see :ref:`run-a-test`. The number increments for each
``download`` call on the same instance.

For release assets, pass ``source={"repository": "OWNER/REPO", "tag": "TAG"}``
to ``list_artifacts`` or ``download``. ``download`` caches extracted release
assets under ``HW_TEST_CACHE_DIR/releases`` (or ``XDG_CACHE_HOME/hw-test/releases``).
``Images`` normally handles this for you through ``artifacts.toml``.

Image roles: ``hw_tests.images``
--------------------------------

Use ``Images(context, github)`` when the same test can consume different build
systems. Its ``flavor`` property is ``context["flavor"]`` if set, otherwise the
last component of ``github.owner_repository``. ``Images`` reads
``tests/<category>/artifacts.toml``, where ``category`` is the first segment of
``context["name"]``.

.. list-table:: ``Images`` calls
   :header-rows: 1

   * - Call
     - Returns or does
   * - ``get(role)``
     - Finds and downloads the role's artifact, then returns the matching file
       as a ``Path``. Roles include ``spl``, ``uboot``, ``kernel``, and ``dtb``
       where the descriptor defines them.
   * - ``artifact_path(role)``
     - Returns that role's path *inside* the extracted artifact as a POSIX
       string. Resolves the role first if needed.
   * - ``flavor``
     - The chosen descriptor section name.

A descriptor entry supplies an artifact-name glob and a file-path glob. When
several artifacts or files match, ``needs`` helps narrow them to the board.
``Images`` skips the test with ``pytest.skip`` for an unknown flavor or missing
role; a missing descriptor, missing file, or ambiguous match fails the test.
For local files without a build run, set ``flavor`` explicitly in the context.
For descriptor syntax, including release-backed roles, see :ref:`write-a-test`.

``find_one(items, what, needs=())`` is the selection helper used by ``Images``.
It returns the sole match, using ``needs`` to narrow multiple candidates. It
raises ``AssertionError`` when nothing or several items remain. Most tests
should use ``Images.get`` instead.

Cloudsmith packages: ``hw_tests.cloudsmith``
--------------------------------------------

``Cloudsmith()`` authenticates at construction. It uses
``CLOUDSMITH_API_KEY`` when set. In Actions, with no API key, it can exchange a
GitHub OIDC token when ``CLOUDSMITH_SERVICE_SLUG`` is set; this also needs
``CLOUDSMITH_NAMESPACE`` and ``id-token: write``. With neither credential it
can access public packages only. A supplied token is validated immediately,
so an invalid one raises an HTTP error during construction.

``download(repository, name, version=None, tags=(), path=None)`` looks in
``CLOUDSMITH_NAMESPACE/repository`` for the newest matching package and
returns the destination **directory** as a ``Path``. It saves the package as
``<directory>/<name>`` and extracts it if it is ZIP or tar. ``path`` chooses
the directory; otherwise a temporary directory is created. Provide either
``version`` or ``tags``:

.. code:: python

   from hw_tests.cloudsmith import Cloudsmith

   package_dir = Cloudsmith().download(
       repository="linux",
       name="sc598-som-ezkit_defconfig-gcc-arm64",
       version="refs/heads/adsp-6.18.31-y",
   )

* A full 40-character SHA matches the package version exactly.
* A ``refs/heads/*`` or ``refs/tags/*`` value selects the latest push package
  carrying that ref. ``refs/pull/*`` selects a pull-request package.
* Another version string is used as a version query on push packages.
* If ``version`` is omitted, every supplied tag must match.

A missing namespace or both missing ``version`` and ``tags`` raises
``ValueError``; no matching package raises ``LookupError``. API and download
failures raise ``requests.HTTPError``. ``get_api_token(org_name,
cs_service_slug, id_token, api_host="api.cloudsmith.io")`` exchanges an OIDC
token and returns the Cloudsmith token. ``validate(token,
api_host="api.cloudsmith.io")`` checks a token and returns ``None``.
``authenticate()`` and ``github_oidc()`` rerun the corresponding setup on an
existing instance; ordinary tests only need the constructor and ``download``.

Runner and SSH helpers
----------------------

These functions support pytest collection and hardware-host authentication.
They are useful when working on the runner itself; ordinary hardware tests
rarely call them.

``hw_tests.collect``
~~~~~~~~~~~~~~~~~~~~

``load_test_metas()`` reads every ``tests/**/config.toml`` from the current
working directory and returns their raw TOML dictionaries, each with ``_uid``
set to the relative test name. ``paths_match(changed_files, path_block)``
returns whether any path matches any newline-separated glob in ``path_block``.
``match_tests(context, metas)`` returns at most one context per matching test.
It requires a source repository name, branch, and changed files; a matching
``[[repository]]`` rule must have the same name and ``refs/heads/<branch>`` and
at least one matching path. The returned context includes ``name``,
``repository`` with the source SHA (``merge_commit_sha`` preferred over
``head_sha``), and ``workflow_run_url``. ``main()`` reads the JSON ``context``
environment variable and writes a ``tests`` output to ``GITHUB_OUTPUT`` in
Actions. See :ref:`run-tests-in-ci` for the workflow that calls it.

``hw_tests.opkssh`` and ``hw_tests.ssh_config``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``OPKSSH(client=None)`` ensures the ``opkssh`` executable is present, logs in
with GitHub OIDC in Actions, and checks SSH access to ``client.hosts`` when a
client is supplied. Locally it uses your existing SSH credentials. The
constructor is called by ``LabgridClient.acquire()``; tests do not need to call
it. ``authenticate(client=None)`` repeats login and the check.
``check_ssh_auth(client)`` runs a batch SSH probe for each host and raises
``PermissionError`` on failure. ``OPKSSH.ensure()`` downloads the executable
if it is not on ``PATH``.

``SSHConfig(path=ssh_config_path)`` writes host entries to an SSH config file;
``ssh_config_path`` defaults to ``./_ssh_config``. ``configure_host(host)``
sets the options expected for local use or Actions. ``set_host_options(hosts,
options)`` writes or updates a ``Host`` block for the supplied host names and
option mapping. The file is written with mode ``0600``. ``client.ssh_config``
is the config instance used by the acquired board, and ``client.hosts`` holds
the hardware hosts it configured.

``hw_tests.logging``
~~~~~~~~~~~~~~~~~~~~

``register_sensitive(value)`` adds a value to the log redaction list; values
shorter than four characters are ignored. ``redact_text(value)`` returns a
string with registered values, IP addresses, and internal host names redacted.
``GitHub.mask`` is the usual entry point when a test also needs a GitHub Actions
mask. ``set_logging()`` sets the package's console logging and redaction.
``install_log_redaction(handlers)`` and
``install_pytest_log_redaction(config)`` wrap existing logging handlers with
``RedactingFormatter``; the pytest integration calls the latter automatically.
``gha_escape(value, prop=False)`` escapes text for GitHub Actions commands;
``prop=True`` also escapes property separators. ``ColorFormatter`` and
``RedactingFormatter`` are ``logging.Formatter`` subclasses used by those
helpers.

The package also exposes ``hw_tests.__version__`` as a string.
