"""CPU temperature collector — platform dispatcher."""

import sys

if sys.platform == "darwin":
    from perf_glance.collectors.darwin.temperature import *  # noqa: F401,F403
else:
    from perf_glance.collectors.linux.temperature import *  # noqa: F401,F403
