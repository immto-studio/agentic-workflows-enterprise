"""The red-team run's placement hook (chapter 15, step 6): Python imports this at startup when its folder is on
PYTHONPATH, which redteam/run_redteam.py arranges for the processes of a run and nothing else. With
CH15_REDTEAM_PLACEMENT naming a placement file, redteam/place.py puts the variant into the fake module it names
when that module is imported; without it, this does nothing.
"""

import os
import sys
from pathlib import Path

_spec = os.environ.get("CH15_REDTEAM_PLACEMENT")
if _spec:
    _redteam = str(Path(__file__).resolve().parents[1])
    if _redteam not in sys.path:
        sys.path.append(_redteam)
    import place

    place.install(_spec)
