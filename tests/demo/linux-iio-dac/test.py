from hw_tests.opkssh import OPKSSH


def main(context):
    print(f"got {context}")

    opkssh = OPKSSH(host='localhost') # TODO get from labgrid coordinator

    print(f"ready to talk to {opkssh.host}")
    # ssh {opkssh.host} 'echo "hello world!"'
