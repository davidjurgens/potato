"""One module per runtime. ``ALL`` is what the registry loads."""

from potato.runtimes.adapters.external import ADAPTER as _external
from potato.runtimes.adapters.headphone_check import ADAPTER as _headphone_check
from potato.runtimes.adapters.jspsych import ADAPTER as _jspsych

ALL = [_jspsych, _headphone_check, _external]
