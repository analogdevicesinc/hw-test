from hw_tests.run import reformat_named_lists, deep_merge


def test_reformat_named_lists():
    data = {
        'target': 'TEST',
        'repository': [
            {'name': 'linux', 'ref': 'refs/heads/main', 'path': 'drivers/*'},
            {'name': 'hdl', 'ref': 'refs/heads/dev', 'path': 'library/*'},
        ],
        'tags': ['a', 'b', 'c'],
    }
    result = reformat_named_lists(data)
    assert result == {
        'target': 'TEST',
        'repository': {
            'linux': {'ref': 'refs/heads/main', 'path': 'drivers/*'},
            'hdl': {'ref': 'refs/heads/dev', 'path': 'library/*'},
        },
        'tags': ['a', 'b', 'c'],
    }


def test_deep_merge():
    base = {'repository': {'linux': {'ref': 'default'}, 'hdl': {'ref': 'v1'}}}
    override = {'repository': {'linux': {'ref': 'override-sha'}}}
    assert deep_merge(base, override) == {
        'repository': {
            'linux': {'ref': 'override-sha'},
            'hdl': {'ref': 'v1'},
        }
    }


def test_deep_merge_override_replaces_non_dict():
    """When override has a non-dict value, it fully replaces the base."""
    base = {'x': {'nested': True}}
    override = {'x': 'flat'}
    assert deep_merge(base, override) == {'x': 'flat'}


def test_reformat_and_merge():
    meta = {
        'target': 'TEST',
        'repository': [
            {'name': 'linux', 'ref': 'refs/heads/main', 'path': 'arch/*\n'},
            {'name': 'u-boot', 'ref': 'refs/heads/feature', 'path': 'board/*\n'},
        ],
    }
    context = {
        'name': 'some/testset',
        'repository': {
            'linux': {'ref': 'feature_new'},
        },
    }

    reformatted = reformat_named_lists(meta)
    merged = deep_merge(reformatted, context)

    assert merged['repository']['linux']['ref'] == 'feature_new'
    assert merged['repository']['u-boot'] == {
        'ref': 'refs/heads/feature', 'path': 'board/*\n',
    }
    assert merged['target'] == 'TEST'
