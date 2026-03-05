"""CPU utilization and frequency collector — platform dispatcher."""

import sys

if sys.platform == "darwin":
    from perf_glance.collectors.darwin.cpu import *  # noqa: F401,F403
    from perf_glance.collectors.linux.cpu import CPUSnapshot  # noqa: F401
else:
    from perf_glance.collectors.linux.cpu import *  # noqa: F401,F403
