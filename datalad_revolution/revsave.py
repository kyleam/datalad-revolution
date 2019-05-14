import logging

lgr = logging.getLogger('datalad.revolution.save')

import traceback
_tb = [t[2] for t in traceback.extract_stack()]
if '_generate_extension_api' not in _tb:  # pragma: no cover
    lgr.warn(
        "The module 'datalad_revolution.revsave' is deprecated. "
        'The `RevSave` class can be imported with: '
        '`from datalad.core.local.save import Save as RevSave`')

from datalad.interface.base import (
    build_doc,
)
from datalad.interface.utils import eval_results
from .dataset import (
    rev_datasetmethod,
)

from datalad.core.local.save import Save


@build_doc
class RevSave(Save):

    @staticmethod
    @rev_datasetmethod(name='rev_save')
    @eval_results
    def __call__(path=None,
                 message=None,
                 dataset=None,
                 version_tag=None,
                 recursive=False,
                 recursion_limit=None,
                 updated=False,
                 message_file=None,
                 to_git=None):
        for r in Save.__call__(path=path,
                               message=message,
                               dataset=dataset,
                               version_tag=version_tag,
                               recursive=recursive,
                               recursion_limit=recursion_limit,
                               updated=updated,
                               message_file=message_file,
                               to_git=to_git,
                               result_renderer=None,
                               result_xfm=None,
                               on_failure="ignore",
                               return_type='generator'):
            yield r
