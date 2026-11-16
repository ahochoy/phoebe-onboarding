"""Single source of truth for queue and sweep timings (Terraform uses these numbers).

Invariant: a document may legitimately stay `processing` for roughly
visibility timeout x max receives while SQS retries it, so the sweeper's stale
threshold must exceed that.
"""

from datetime import timedelta

WORKER_TIMEOUT_S = 120
QUEUE_VISIBILITY_TIMEOUT_S = 720  # 6x the worker timeout
MAX_RECEIVE_COUNT = 3
SWEEP_INTERVAL = timedelta(hours=1)
STALE_PROCESSING = timedelta(minutes=60)
