import logging

import traceback
lgr = logging.getLogger('datalad.revolution.run')

_tb = [t[2] for t in traceback.extract_stack()]
if '_generate_extension_api' not in _tb:  # pragma: no cover
    lgr.warn(
        "The module 'datalad_revolution.revrun' is deprecated. "
        'The `RevRun` class can be imported with: '
        '`from datalad.interface.run import Run as RevRun`')

from datalad.interface.base import (
    build_doc,
)
from datalad.interface.utils import eval_results
from .dataset import (
    rev_datasetmethod,
)

from datalad.interface.run import Run


@build_doc
class RevRun(Run):

    @staticmethod
    @rev_datasetmethod(name='rev_run')
    @eval_results
    def __call__(cmd=None,
                 dataset=None,
                 inputs=None,
                 outputs=None,
                 expand=None,
                 explicit=False,
                 message=None,
                 sidecar=None):
        for r in Run.__call__(cmd=cmd,
                              dataset=dataset,
                              inputs=inputs,
                              outputs=outputs,
                              expand=expand,
                              explicit=explicit,
                              message=message,
                              sidecar=sidecar,
                              result_renderer=None,
                              result_xfm=None,
                              on_failure="ignore",
                              return_type='generator'):
            yield r
