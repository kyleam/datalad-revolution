# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Test status command"""

import os.path as op
import datalad_revolution.utils as ut

from datalad.utils import (
    chpwd,
    on_windows,
)
from datalad.tests.utils import (
    eq_,
    assert_in,
    assert_raises,
    assert_status,
    assert_result_count,
    with_tempfile,
)
from datalad.support.exceptions import (
    NoDatasetArgumentFound,
    IncompleteResultsError,
)
from datalad_revolution.dataset import RevolutionDataset as Dataset
from datalad_revolution.tests.utils import (
    get_deeply_nested_structure,
)
from datalad.api import (
    rev_status as status,
)


@with_tempfile(mkdir=True)
@with_tempfile()
@with_tempfile(mkdir=True)
def test_status_basics(path, linkpath, otherdir):
    if not on_windows:
        # make it more complicated by default
        ut.Path(linkpath).symlink_to(path, target_is_directory=True)
        path = linkpath

    with chpwd(path):
        assert_raises(NoDatasetArgumentFound, status)
    ds = Dataset(path).rev_create()
    # outcome identical between ds= and auto-discovery
    with chpwd(path):
        assert_raises(IncompleteResultsError, status, path=otherdir)
        stat = status()
    eq_(stat, ds.rev_status())
    assert_status('ok', stat)
    # we have a bunch of reports (be vague to be robust to future changes
    assert len(stat) > 2
    # check the composition
    for s in stat:
        # all paths are native path objects
        assert isinstance(s['path'], ut.Path)
        eq_(s['status'], 'ok')
        eq_(s['action'], 'status')
        eq_(s['state'], 'clean')
        eq_(s['type'], 'file')
        assert_in('gitshasum', s)
        eq_(s['refds'], ds.pathobj)


@with_tempfile(mkdir=True)
@with_tempfile(mkdir=True)
def test_status_nods(path, otherpath):
    ds = Dataset(path).rev_create()
    assert_result_count(
        ds.rev_status(path=otherpath, on_failure='ignore'),
        1,
        status='error',
        message='path not underneath this dataset')
    otherds = Dataset(otherpath).rev_create()
    assert_result_count(
        ds.rev_status(path=otherpath, on_failure='ignore'),
        1,
        path=otherds.path,
        status='error',
        message=(
            'dataset containing given paths is not underneath the reference dataset %s: %s',
            ds, [])
        )


@with_tempfile(mkdir=True)
@with_tempfile()
def test_status(_path, linkpath):
    # do the setup on the real path, not the symlink to have its
    # bugs not affect this test of status()
    ds = get_deeply_nested_structure(str(_path))
    if not on_windows:
        # make it more complicated by default
        ut.Path(linkpath).symlink_to(_path, target_is_directory=True)
        path = linkpath
    else:
        path = _path

    ds = Dataset(path)
    if not on_windows:
        # check the premise of this test
        assert ds.pathobj != ds.repo.pathobj

    # bunch of smoke tests
    plain_recursive = ds.rev_status(recursive=True)
    # query of '.' is same as no path
    eq_(plain_recursive, ds.rev_status(path='.', recursive=True))
    # duplicate paths do not change things
    eq_(plain_recursive, ds.rev_status(path=['.', '.'], recursive=True))
    # neither do nested paths
    eq_(plain_recursive,
        ds.rev_status(path=['.', 'subds_modified'], recursive=True))
    # when invoked in a subdir of a dataset it still reports on the full thing
    # just like `git status`, as long as there are no paths specified
    with chpwd(op.join(path, 'directory_untracked')):
        plain_recursive = status(recursive=True)
    # should be able to take absolute paths and yield the same
    # output
    eq_(plain_recursive, ds.rev_status(path=ds.path, recursive=True))

    # query for a deeply nested path from the top, should just work with a
    # variety of approaches
    rpath = op.join('subds_modified', 'subds_lvl1_modified',
                    'directory_untracked')
    apathobj = ds.pathobj / rpath
    apath = str(apathobj)
    # ds.repo.pathobj will have the symlink resolved
    arealpath = ds.repo.pathobj / rpath
    # TODO include explicit relative path in test
    for p in (rpath, apath, arealpath, None):
        if p is None:
            # change into the realpath of the dataset and
            # query with an explicit path
            with chpwd(ds.repo.path):
                res = ds.rev_status(path=op.join('.', rpath))
        else:
            res = ds.rev_status(path=p)
        assert_result_count(
            res,
            1,
            state='untracked',
            type='directory',
            refds=ds.pathobj,
            # path always comes out a full path inside the queried dataset
            path=apathobj,
        )

    assert_result_count(
        ds.rev_status(
            recursive=True),
        1,
        path=apathobj)
    # limiting recursion will exclude this particular path
    assert_result_count(
        ds.rev_status(
            recursive=True,
            recursion_limit=1),
        0,
        path=apathobj)
    # negative limit is unlimited limit
    eq_(
        ds.rev_status(recursive=True, recursion_limit=-1),
        ds.rev_status(recursive=True)
    )