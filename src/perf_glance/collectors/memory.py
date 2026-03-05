"""Memory (RAM and swap) collector — platform dispatcher."""

import sys

if sys.platform == "darwin":
    from perf_glance.collectors.darwin.memory import *  # noqa: F401,F403
    from perf_glance.collectors.linux.memory import MemorySnapshot  # noqa: F401
else:
    from perf_glance.collectors.linux.memory import *  # noqa: F401,F403
