"""
deli - Lightweight load execution engine. Speed and performance first.

Not a framework: minimal abstraction, direct execution path, bounded memory.
Postman Collection v2.1, async HTTP/2, load/stress scenarios, HTML reports.
"""

from .exceptions import DeliCollectionError, DeliConfigError, DeliError, DeliRunnerError

__all__ = [
    "__version__",
    "DeliCollectionError",
    "DeliConfigError",
    "DeliError",
    "DeliRunnerError",
]

__version__ = "1.0.0"
__author__ = "Cuma Kurt"
__email__ = "cumakurt@gmail.com"
