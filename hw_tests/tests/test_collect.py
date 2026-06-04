
from hw_tests.collect import load_test_metas, match_tests


CONTEXT_LINUX_DAC = {
    "owner": "analogdevicesinc",
    "repository": "linux",
    "branch": "mirror_ci/jic23/iio/testing",
    "head_sha": "010c31d76bfb49bb2c53cc4cb9a0ae63031a6ead",
    "base_sha": "ae8360f3715aa61714864fc81f39790cbb883d40",
    "changed_files": (
        "Documentation/ABI/testing/sysfs-bus-iio\n"
        "Documentation/devicetree/bindings/iio/dac/adi,ad3530r.yaml\n"
        "drivers/iio/dac/Kconfig\n"
        "drivers/iio/dac/ad3530r.c"
    ),
    "pr": "3177",
    "state": "",
    "is_fork": "",
    "merge_commit_sha": "",
    "base_branch_head_sha": "83e04bccee664e7f526c56bfab33eb84903ee848",
}


def test_linux_dac_matches():
    metas = load_test_metas()
    results = match_tests(CONTEXT_LINUX_DAC, metas)

    assert len(results) == 1
    result = results[0]
    assert result["name"] == "demo/linux-iio-dac"
    assert result["with"]["linux"]["ref"] == CONTEXT_LINUX_DAC["head_sha"]


def test_no_match_wrong_ref():
    print(load_test_metas())
    context = {**CONTEXT_LINUX_DAC, "branch": "some-other-branch"}
    results = match_tests(context, load_test_metas())
    assert results == []


def test_no_match_wrong_repo():
    context = {**CONTEXT_LINUX_DAC, "repository": "hdl"}
    results = match_tests(context, load_test_metas())
    assert results == []


def test_no_match_unrelated_files():
    context = {**CONTEXT_LINUX_DAC, "changed_files": "net/core/skbuff.c"}
    results = match_tests(context, load_test_metas())
    assert results == []


def test_merge_commit_sha_takes_precedence():
    merge_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    context = {**CONTEXT_LINUX_DAC, "merge_commit_sha": merge_sha}
    results = match_tests(context, load_test_metas())
    assert results[0]["with"]["linux"]["ref"] == merge_sha
