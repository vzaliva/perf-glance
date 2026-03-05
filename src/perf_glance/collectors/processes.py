"""Process list collector — platform dispatcher."""

import sys

if sys.platform == "darwin":
    from perf_glance.collectors.darwin.processes import *  # noqa: F401,F403
    from perf_glance.collectors.linux.processes import ProcessInfo  # noqa: F401
else:
    from perf_glance.collectors.linux.processes import *  # noqa: F401,F403
