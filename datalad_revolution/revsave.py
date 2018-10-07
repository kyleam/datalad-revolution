# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Interface to add content, and save modifications to a dataset

"""

__docformat__ = 'restructuredtext'

import logging

from datalad.interface.base import (
    Interface,
    build_doc,
)
from datalad.interface.common_opts import (
    recursion_limit,
    recursion_flag,
    save_message_opt,
)
from datalad.interface.results import get_status_dict
from datalad.interface.utils import eval_results
from datalad.support.param import Parameter
from datalad.support.constraints import (
    EnsureStr,
    EnsureNone,
)

from datalad_revolution.dataset import (
    EnsureDataset,
    datasetmethod,
    require_dataset,
)

lgr = logging.getLogger('datalad.revolution.save')


@build_doc
class RevSave(Interface):
    """Save the current state of a dataset

    Saving the state of a dataset records changes that have been made to it.
    This change record is annotated with a user-provided description.
    Optionally, an additional tag, such as a version, can be assigned to the
    saved state. Such tag enables straightforward retrieval of past versions at
    a later point in time.

    Examples:

      Save any content underneath the current directory, without altering
      any potential subdataset (use --recursive for that)::

        % datalad save .

      Save any modification of known dataset content, but leave untracked
      files (e.g. temporary files) untouched::

        % dataset save -d <path_to_dataset>

      Tag the most recent saved state of a dataset::

        % dataset save -d <path_to_dataset> --version-tag bestyet
    """

    _params_ = dict(
        dataset=Parameter(
            args=("-d", "--dataset"),
            doc=""""specify the dataset to save""",
            constraints=EnsureDataset() | EnsureNone()),
        path=Parameter(
            args=("path",),
            metavar='PATH',
            doc="""path/name of the dataset component to save. If given, only
            changes made to those components are recorded in the new state.""",
            nargs='*',
            constraints=EnsureStr() | EnsureNone()),
        message=save_message_opt,
        message_file=Parameter(
            args=("-F", "--message-file"),
            doc="""take the commit message from this file. This flag is
            mutually exclusive with -m.""",
            constraints=EnsureStr() | EnsureNone()),
        version_tag=Parameter(
            args=("--version-tag",),
            metavar='ID',
            doc="""an additional marker for that state.""",
            constraints=EnsureStr() | EnsureNone()),
        recursive=recursion_flag,
        recursion_limit=recursion_limit,
        updated=Parameter(
            args=('-u', '--updated',),
            action='store_true',
            doc="""if given, only saves previously tracked paths."""),

    )

    @staticmethod
    @datasetmethod(name='rev_save')
    @eval_results
    def __call__(message=None, path=None, dataset=None,
                 version_tag=None,
                 recursive=False, recursion_limit=None,
                 updated=False,
                 message_file=None
                 ):
        if message and message_file:
            raise ValueError(
                "Both a message and message file were specified for save()")

        if message_file:
            with open(message_file) as mfh:
                message = mfh.read()

        # we want 'normal' to achieve the most compact argument list
        # for git calls
        untracked_mode = 'no' if updated else 'normal'

        # there are three basic scenarios:
        # 1. save modifications to any already tracked content
        # 2. save any content (including removal of deleted content)
        #    to bring things to a clean state
        # 3. like (2), but only operate on a given subset of content
        #    identified by paths
        # - all three have to work in conjunction with --recursive
        # - the difference between (1) and (2) should be no more
        #   that a switch from --untracked=no to --untracked=all
        #   in Repo.save()

        # we do not support
        # - simultaneous operations on multiple datasets from disjoint
        #   dataset hierarchies, hence a single reference dataset must be
        #   identifiable from the either
        #   - curdir or
        #   - the `dataset` argument.
        #   This avoids complex annotation loops and hierarchy tracking.
        # - any modification upwards from the root dataset

        # disambiguation of path arguments:
        # - when a subdataset root is given as a path to save, it is
        #   interpreted as instructions to save the present subdataset
        #   commit as the state referenced in the parent
        # - when the same path is given with --recursive, the subdataset's
        #   content itself will be saved first before recording the new
        #   state in the parent

        ds = require_dataset(dataset, check_installed=True, purpose='saving')

        # TODO track if anything happened and issue 'notneeded' if not

        if not recursive:
            for res in ds.repo.save(
                    message=message,
                    paths=path,
                    # TODO make decision whether we want this parameter
                    # it would complicate things quite a bit, maybe only
                    # allow for it in the context of explicitly provided
                    # paths
                    #git=to_git
                    untracked=untracked_mode):
                # TODO normalize results
                yield res
            # TODO add tag, if desired
            return
