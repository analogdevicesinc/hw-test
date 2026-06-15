from hw_tests.opkssh import OPKSSH
from hw_tests.cloudsmith import Cloudsmith


def main(context):
    print(f"got {context}")

    opkssh = OPKSSH(host='localhost') # TODO get from labgrid coordinator

    print(f"ready to talk to {opkssh.host}")
    # ssh {opkssh.host} 'echo "hello world!"'

    Cloudsmith()
    print("ready to talk do cloudsmith stuff")
