"""The two caches. `django.core.cache.cache` (default) is the shared DatabaseCache table `django_cache`: sign in
codes, attempt counters and the throttles that guard them, so every Cloud Run instance sees the same counts.
`local` is this process's memory, for what is cheap to rebuild and read on every request (the map and feed
payloads, the clock row, the high volume throttles), so those never cost a database round trip."""
from django.core.cache import caches
from django.utils.connection import ConnectionProxy

local = ConnectionProxy(caches, 'local')
