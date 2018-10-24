__docformat__ = 'restructuredtext'


import os.path as op
from collections import OrderedDict
import logging
import re
from six import (
    iteritems,
    text_type,
)
from weakref import WeakValueDictionary

from datalad.dochelpers import exc_str
import datalad_revolution.utils as ut
from datalad.support.gitrepo import (
    GitRepo,
    InvalidGitRepositoryError,
)
from datalad.support.exceptions import CommandError
from datalad.interface.results import get_status_dict

lgr = logging.getLogger('datalad.revolution.gitrepo')

obsolete_methods = (
    'is_dirty',
)


class RevolutionGitRepo(GitRepo):

    # Begin Flyweight:
    _unique_instances = WeakValueDictionary()
    # End Flyweight:

    def __init__(self, *args, **kwargs):
        super(RevolutionGitRepo, self).__init__(*args, **kwargs)
        # the sole purpose of this init is to add a pathlib
        # native path object to the instance
        # XXX this relies on the assumption that self.path as managed
        # by the base class is always a native path
        self.pathobj = ut.Path(self.path)

    def get_content_info(self, paths=None, ref=None, untracked='all'):
        """Get identifier and type information from repository content.

        This is simplified front-end for `git ls-files/tree`.

        Parameters
        ----------
        paths : list
          Specific paths to query info for. In none are given, info is
          reported for all content.
        ref : gitref or None
          If given, content information is retrieved for this Git reference
          (via ls-tree), otherwise content information is produced for the
          present work tree (via ls-files).
        untracked : {'no', 'normal', 'all'}
          If and how untracked content is reported when no `ref` was given:
          'no': no untracked files are reported; 'normal': untracked files
          and entire untracked directories are reported as such; 'all': report
          individual files even in fully untracked directories.

        Returns
        -------
        dict
          Each content item has an entry under its relative path within
          the repository. Each value is a dictionary with properties:

          `type`
            Can be 'file', 'symlink', 'dataset', 'directory'

            Note that the reported type will not always match the type of
            content commited to Git, rather it will reflect the nature
            of the content minus platform/mode-specifics. For example,
            a symlink to a locked annexed file on Unix will have a type
            'file', reported, while a symlink to a file in Git or directory
            will be of type 'symlink'.

          `gitshasum`
            SHASUM of the item as tracked by Git, or None, if not
            tracked. This could be different from the SHASUM of the file
            in the worktree, if it was modified.
        """
        # TODO limit by file type to replace code in subdatasets command
        info = OrderedDict()

        mode_type_map = {
            '100644': 'file',
            '100755': 'file',
            '120000': 'symlink',
            '160000': 'dataset',
        }

        # this will not work in direct mode, but everything else should be
        # just fine
        if not ref:
            # --exclude-standard will make sure to honor and standard way
            # git can be instructed to ignore content, and will prevent
            # crap from contaminating untracked file reports
            cmd = ['git', 'ls-files',
                   '--stage', '-z', '-d', '-m', '--exclude-standard']
            # untracked report mode, using labels from `git diff` option style
            if untracked == 'all':
                cmd.append('-o')
            elif untracked == 'normal':
                cmd += ['-o', '--directory']
            elif untracked == 'no':
                pass
            else:
                raise ValueError(
                    'unknown value for `untracked`: %s', untracked)
        else:
            cmd = ['git', 'ls-tree', ref, '-z', '-r', '--full-tree']
        # works for both modes
        props_re = re.compile(r'([0-9]+) (.*) (.*)\t(.*)$')

        stdout, stderr = self._git_custom_command(
            [str(f) for f in paths] if paths else [],
            cmd,
            log_stderr=True,
            log_stdout=True,
            # not sure why exactly, but log_online has to be false!
            log_online=False,
            expect_stderr=False,
            shell=False,
            # we don't want it to scream on stdout
            expect_fail=True)

        for line in stdout.split('\0'):
            if not line:
                continue
            inf = {}
            props = props_re.match(line)
            if not props:
                # not known to Git, but Git always reports POSIX
                path = ut.PurePosixPath(line)
                inf['gitshasum'] = None
            else:
                # again Git reports always in POSIX
                path = ut.PurePosixPath(props.group(4))
                inf['gitshasum'] = props.group(2 if not ref else 3)
                inf['type'] = mode_type_map.get(
                    props.group(1), props.group(1))
                if inf['type'] == 'symlink' and \
                        '.git/annex/objects' in \
                        ut.Path(
                            op.realpath(op.join(self.path, str(path)))
                            ).as_posix():
                    # ugly thing above could be just
                    #  (self.pathobj / path).resolve().as_posix()
                    # but PY3.5 does not support resolve(strict=False)

                    # report locked annexed files as file, their
                    # symlink-nature is a technicality that is dependent
                    # on the particular mode annex is in
                    inf['type'] = 'file'

            # join item path with repo path to get a universally useful
            # path representation with auto-conversion and tons of other
            # stuff
            path = self.pathobj.joinpath(path)
            if 'type' not in inf:
                # be nice and assign types for untracked content
                inf['type'] = 'symlink' if path.is_symlink() \
                    else 'directory' if path.is_dir() else 'file'
            info[path] = inf

        # final loop to filter out reports on paths (that where given)
        # that do not belong to this repo (which status() would turn into
        if paths is not None and ref is not None:
            # dedicated paths were queried, but ls-tree would respond with
            # an entry for each path that is actually contained in a
            # submodule with a report on the respective subdataset path
            # -> only report on paths that were actually queried
            paths = {self.pathobj / p for p in paths}
            info = {k: v for k, v in iteritems(info)
                    if k in paths or v.get('type', None) != 'dataset'}
        return info

    def status(self, paths=None, untracked='all', ignore_submodules='no'):
        """Simplified `git status` equivalent.

        Parameters
        ----------
        paths : list or None
          If given, limits the query to the specified paths. To query all
          paths specify `None`, not an empty list.
        untracked : {'no', 'normal', 'all'}
          If and how untracked content is reported when no `ref` was given:
          'no': no untracked files are reported; 'normal': untracked files
          and entire untracked directories are reported as such; 'all': report
          individual files even in fully untracked directories.
        ignore_submodules : {'no', 'other', 'all'}

        Returns
        -------
        dict
          Each content item has an entry under its relative path within
          the repository. Each value is a dictionary with properties:

          `type`
            Can be 'file', 'symlink', 'dataset', 'directory'
          `state`
            Can be 'added', 'untracked', 'clean', 'deleted', 'modified'.
        """
        lgr.debug('Query status of %r for %s paths',
                  self, len(paths) if paths else 'all')
        return self.diffstatus(
            fr='HEAD',
            to=None,
            paths=paths,
            untracked=untracked,
            ignore_submodules=ignore_submodules)

    def diff(self, fr, to, paths=None, untracked='all',
             ignore_submodules='no'):
        """Like status(), but reports changes between to arbitrary revisions

        Parameters
        ----------
        fr : str
          Revision specification (anything that Git understands).
        to : str or None
          Revision specification (anything that Git understands), or None
          to compare to the state of the work tree.
        paths : list or None
          If given, limits the query to the specified paths. To query all
          paths specify `None`, not an empty list.
        untracked : {'no', 'normal', 'all'}
          If and how untracked content is reported when no `ref` was given:
          'no': no untracked files are reported; 'normal': untracked files
          and entire untracked directories are reported as such; 'all': report
          individual files even in fully untracked directories.
        ignore_submodules : {'no', 'other', 'all'}

        Returns
        -------
        dict
          Each content item has an entry under its relative path within
          the repository. Each value is a dictionary with properties:

          `type`
            Can be 'file', 'symlink', 'dataset', 'directory'
          `state`
            Can be 'added', 'untracked', 'clean', 'deleted', 'modified'.
        """
        return {k: v for k, v in iteritems(self.diffstatus(
            fr=fr, to=to, paths=paths,
            untracked=untracked,
            ignore_submodules=ignore_submodules))
            if v.get('state', None) != 'clean'}

    def diffstatus(self, fr, to, paths=None, untracked='all',
                   ignore_submodules='no', _cache=None):
        """Like diff(), but reports the status of 'clean' content too"""
        def _get_cache_key(label, paths, ref, untracked=None):
            return self.path, label, tuple(paths) if paths else None, \
                ref, untracked

        if _cache is None:
            _cache = {}
        # TODO report more info from get_content_info() calls in return
        # value, those are cheap and possibly useful to a consumer
        status = OrderedDict()
        # we need (at most) three calls to git
        if to is None:
            # everything we know about the worktree, including os.stat
            # for each file
            key = _get_cache_key('ci', paths, None, untracked)
            if key in _cache:
                to_state = _cache[key]
            else:
                to_state = self.get_content_info(
                    paths=paths, ref=None, untracked=untracked)
                _cache[key] = to_state
            # we want Git to tell us what it considers modified and avoid
            # reimplementing logic ourselves
            key = _get_cache_key('mod', paths, None)
            if key in _cache:
                modified = _cache[key]
            else:
                modified = set(
                    self.pathobj.joinpath(ut.PurePosixPath(p))
                    for p in self._git_custom_command(
                        # low-level code cannot handle pathobjs
                        [str(p) for p in paths] if paths else None,
                        ['git', 'ls-files', '-z', '-m'])[0].split('\0')
                    if p)
                _cache[key] = modified
        else:
            key = _get_cache_key('ci', paths, to)
            if key in _cache:
                to_state = _cache[key]
            else:
                to_state = self.get_content_info(paths=paths, ref=to)
                _cache[key] = to_state
            # we do not need worktree modification detection in this case
            modified = None
        # origin state
        key = _get_cache_key('ci', paths, fr)
        if key in _cache:
            from_state = _cache[key]
        else:
            from_state = self.get_content_info(paths=paths, ref=fr)
            _cache[key] = to_state

        for f, to_state_r in iteritems(to_state):
            props = None
            if f not in from_state:
                # this is new, or rather not known to the previous state
                props = dict(
                    state='added' if to_state_r['gitshasum'] else 'untracked',
                    type=to_state_r['type'],
                )
            elif to_state_r['gitshasum'] == from_state[f]['gitshasum'] and \
                    (modified is None or f not in modified):
                if ignore_submodules != 'all' or to_state_r['type'] != 'dataset':
                    # no change in git record, and no change on disk
                    props = dict(
                        state='clean' if f.exists() or
                              f.is_symlink() else 'deleted',
                        type=to_state_r['type'],
                    )
            else:
                # change in git record, or on disk
                props = dict(
                    # TODO is 'modified' enough, should be report typechange?
                    # often this will be a pointless detail, though...
                    # TODO we could have a new file that is already staged
                    # but had subsequent modifications done to it that are
                    # unstaged. Such file would presently show up as 'added'
                    # ATM I think this is OK, but worth stating...
                    state='modified' if f.exists() or
                    f.is_symlink() else 'deleted',
                    # TODO record before and after state for diff-like use
                    # cases
                    type=to_state_r['type'],
                )
            if props['state'] in ('clean', 'added'):
                props['gitshasum'] = to_state_r['gitshasum']
            status[f] = props

        for f, from_state_r in iteritems(from_state):
            if f not in to_state:
                # we new this, but now it is gone and Git is not complaining
                # about it being missing -> properly deleted and deletion
                # stages
                status[f] = dict(
                    state='deleted',
                    type=from_state_r['type'],
                    # report the shasum to distinguish from a plainly vanished
                    # file
                    gitshasum=from_state_r['gitshasum'],
                )

        if ignore_submodules == 'all':
            return status

        # loop over all subdatasets and look for additional modifications
        for f, st in iteritems(status):
            if not (st['type'] == 'dataset' and st['state'] == 'clean' and
                    GitRepo.is_valid_repo(str(f))):
                # no business here
                continue
            # we have to recurse into the dataset and get its status
            subrepo = RevolutionGitRepo(str(f))
            # subdataset records must be labeled clean up to this point
            if st['gitshasum'] != subrepo.get_hexsha():
                # current commit in subdataset deviates from what is
                # recorded in the dataset, cheap test
                st['state'] = 'modified'
            else:
                # the recorded commit did not change, so we need to make
                # a more expensive traversal
                rstatus = subrepo.diffstatus(
                    # we can use 'HEAD' because we know that the commit
                    # did not change. using 'HEAD' will facilitate
                    # caching the result
                    fr='HEAD',
                    to=None,
                    paths=None,
                    untracked=untracked,
                    # TODO could be RF'ed to stop after the first find
                    # of a modified subdataset
                    # ATM implementation performs an exhaustive search
                    ignore_submodules='other',
                    _cache=_cache)
                if any(v['state'] != 'clean'
                       for k, v in iteritems(rstatus)):
                    st['state'] = 'modified'
            if ignore_submodules == 'other' and st['state'] == 'modified':
                # we know for sure that at least one subdataset is modified
                # go home quick
                break
        return status

    def _save_pre(self, paths, _status, **kwargs):
        # helper to get an actionable status report
        if paths is not None and not paths and not _status:
            return
        if _status is None:
            if 'untracked' not in kwargs:
                kwargs['untracked'] = 'normal'
            status = self.status(
                paths=paths,
                **{k: kwargs[k] for k in kwargs
                   if k in ('untracked', 'ignore_submodules')})
        else:
            # we want to be able to add items down the line
            # make sure to detach from prev. owner
            status = _status.copy()
        status = OrderedDict(
            (k, v) for k, v in iteritems(status)
            if v.get('state', None) != 'clean'
        )
        return status

    def _save_post(self, message, status):
        # helper to commit changes reported in status
        _datalad_msg = False
        if not message:
            message = 'Recorded changes'
            _datalad_msg = True

        # TODO remove pathobj stringification when commit() can
        # handle it
        to_commit = [str(f.relative_to(self.pathobj))
                     for f, props in iteritems(status)]
        if to_commit:
            self.commit(
                files=to_commit,
                msg=message,
                _datalad_msg=_datalad_msg,
                options=None,
                # do not raise on empty commit
                # it could be that the `add` in this save-cycle has already
                # brought back a 'modified' file into a clean state
                careless=True,
            )

    def save(self, message=None, paths=None, _status=None, **kwargs):
        """Save dataset content.

        Parameters
        ----------
        message : str or None
          A message to accompany the changeset in the log. If None,
          a default message is used.
        paths : list or None
          Any content with path matching any of the paths given in this
          list will be saved. Matching will be performed against the
          dataset status (GitRepo.status()), or a custom status provided
          via `_status`. If no paths are provided, ALL non-clean paths
          present in the repo status or `_status` will be saved.
        ignore_submodules : {'no', 'all'}
          If `_status` is not given, will be passed as an argument to
          Repo.status(). With 'all' no submodule state will be saved in
          the dataset. Note that submodule content will never be saved
          in their respective datasets, as this function's scope is
          limited to a single dataset.
        _status : dict or None
          If None, Repo.status() will be queried for the given `ds`. If
          a dict is given, its content will be used as a constrain.
          For example, to save only modified content, but no untracked
          content, set `paths` to None and provide a `_status` that has
          no entries for untracked content.
        **kwargs
          Additional arguments that are passed to underlying Repo methods.
          Supported:
          - git : bool (passed to Repo.add()
          - ignore_submodules : {'no', 'other', 'all'}
            passed to Repo.status()
          - untracked : {'no', 'normal', 'all'} - passed to Repo.satus()
        """
        return list(
            self.save_(
                message=message,
                paths=paths,
                _status=_status,
                **kwargs
            )
        )

    def save_(self, message=None, paths=None, _status=None, **kwargs):
        status = self._save_pre(paths, _status, **kwargs)
        if not status:
            # all clean, nothing todo
            lgr.debug('Nothing to save in %r, exiting early', self)
            return

        # three things are to be done:
        # - add (modified/untracked)
        # - remove (deleted if not already staged)
        # - commit (with all paths that have been touched, to bypass
        #   potential pre-staged bits)

        # looks for contained repositories
        to_add_submodules = [sm for sm, sm_props in iteritems(
            self.get_content_info(
                # get content info for any untracked directory
                [f for f, props in iteritems(status)
                 if props.get('state', None) == 'untracked' and
                 props.get('type', None) == 'directory'],
                ref=None,
                # request exhaustive list, so that everything that is
                # still reported as a directory must be its own repository
                untracked='all'))
            if sm_props.get('type', None) == 'directory']
        added_submodule = False
        for cand_sm in to_add_submodules:
            try:
                self.add_submodule(
                    str(cand_sm.relative_to(self.pathobj)),
                    url=None, name=None)
            except (CommandError, InvalidGitRepositoryError) as e:
                yield get_status_dict(
                    action='add_submodule',
                    ds=self,
                    path=self.pathobj / ut.PurePosixPath(cand_sm),
                    status='error',
                    message=e.stderr if hasattr(e, 'stderr')
                    else ('not a Git repository: %s', exc_str(e)),
                    logger=lgr)
                continue
            added_submodule = True
        if added_submodule:
            # need to include .gitmodules in what needs saving
            status[self.pathobj.joinpath('.gitmodules')] = dict(
                type='file', state='modified')
        to_add = [
            # TODO remove pathobj stringification when add() can
            # handle it
            str(f.relative_to(self.pathobj))
            for f, props in iteritems(status)
            if props.get('state', None) in ('modified', 'untracked')]
        if to_add:
            lgr.debug('%i paths to add to %r %s',
                len(to_add), self, to_add if len(to_add) < 10 else '')
            for r in self.add_(
                    to_add,
                    git_options=None,
                    # this would possibly counteract our own logic
                    update=False,
                    **{k: kwargs[k] for k in kwargs if k in ('git',)}):
                yield get_status_dict(
                    action=r.get('command', 'add'),
                    refds=self.pathobj,
                    type='file',
                    path=(self.pathobj / ut.PurePosixPath(r['file']))
                    if 'file' in r else None,
                    status='ok' if r.get('success', None) else 'error',
                    key=r.get('key', None),
                    logger=lgr)

        to_remove = [
            # TODO remove pathobj stringification when delete() can
            # handle it
            str(f.relative_to(self.pathobj))
            for f, props in iteritems(status)
            if props.get('state', None) == 'deleted' and
            # staged deletions have a gitshasum reported for them
            # those should not be processed as git rm will error
            # due to them being properly gone already
            not props.get('gitshasum', None)]
        if to_remove:
            for r in self.remove(
                    to_remove,
                    # we would always see individual files
                    recursive=False):
                # TODO normalize result
                yield r

        self._save_post(message, status)
        # TODO yield result for commit, prev helper checked hexsha pre
        # and post...

    # run() needs this ATM, but should eventually be RF'ed to a
    # status(recursive=True) call
    @property
    def dirty(self):
        return len([
            p for p, props in iteritems(self.status(
                untracked='normal', ignore_submodules='other'))
            if props.get('state', None) != 'clean']) > 0


# remove deprecated methods from API
for m in obsolete_methods:
    if hasattr(RevolutionGitRepo, m):
        setattr(RevolutionGitRepo, m, ut.nothere)
