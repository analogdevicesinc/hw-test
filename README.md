# Hardware tests

Run hardware tests based on events, with changed-files test selection.

## Workflows

- `run-test.yml`: Run one individual test, takes as input the test name, e.g., `demo/linux-iio-dac`
- `run-tests.yml`: Collect tests and run each in a matrix, the input is a `workflow_run` url (`https://api.github.com/repos/**/actions/runs/*`)

The `run-tests.yml` uses [doctools/workflow-run-to-context](https://github.com/analogdevicesinc/doctools/tree/action/workflow-run-to-context) to resolve, through API calls, the changed files set and relevant shas for `push` and `pull_request` events.

## Test topology

Each set contains:

- `config.toml`: Meta configuration of the test, contains the conditions when it should run, as well as default values (for example, activated by `linux` event, fill `hdl` with the default, and vice-versa).
- `test.py`: The actual test file, has a `main` top-level method that takes `context` as the input.

The path (`path/to/some-test`) is the uid of the test.

A context has the format:

```{json}
{
  'name': 'demo/linux-iio-dac',
  'with': {
    'linux': {'ref': '010c31d76bfb49bb2c53cc4cb9a0ae63031a6ead'},
    'hdl': {'ref': 'refs/heads/main'}}}
  }
}
```

The `hw_tests/run.py`, before invoking `tests/**/test.py`, fills the context with the default values (in the example, the `hdl.ref`).
At this point, the individual `test.py` executes its test steps, which may include fetching artifacts, acquiring hardware and communicating through ssh.

## OPKSSH

`opkssh` enables ssh to be used with OpenID Connect allowing SSH access to be managed via identities instead of long-lived SSH keys.
This enables short-lived authentication to hosts, like `labgrid executors`.
Tests that leverage it, simply:

```{python}
# host = some_lib.get_host('example')
# Install opkssh and acquire authentication
opkssh = OPKSSH(host=host)
# ssh {opkssh.host} 'echo "hello world!"'
```

## Labgrid

- `coordinator`: Through `grpc`, acquires hardware and provide a exporter.
- `exporter`: Through `ssh`, manipulates hardware. Authenticated with `opkssh`.
