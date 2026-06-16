import time
from functools import lru_cache, wraps
from typing import Any, Callable, Dict

from ..utils import norm_path
from .format import format_and_order_sync_stat_for_display, format_peer_status_metrics

CACHE_TTL_SECS = 15
PARTIAL_CACHE_MAX = 32


def lru_cache_timeout(ttl_getter: Callable[[], int], maxsize: int = 128):
    def decorator(func):
        @lru_cache(maxsize=maxsize)
        def cached_func(time_token, *args, **kwargs):
            return func(*args, **kwargs)

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                ttl = ttl_getter(*args, **kwargs)
            except TypeError:
                ttl = ttl_getter()
            if not ttl:
                return func(*args, **kwargs)
            time_token = int(time.monotonic() / ttl)
            return cached_func(time_token, *args, **kwargs)

        wrapper.cache_clear = cached_func.cache_clear  # type: ignore[attr-defined]
        wrapper.cache_info = cached_func.cache_info  # type: ignore[attr-defined]
        return wrapper
    return decorator


def _peer_stats_for_dir(metrics, dir_path):
    return metrics.get(dir_path, {}).get('peer', {})


def _requested_peers_have_stats(metrics, peers, dir_path):
    peer_stats = _peer_stats_for_dir(metrics, dir_path)
    return all(peer in peer_stats for peer in peers)


def metrics_for_dir_and_peers(metrics, dir_path, peers):
    result: Dict[str, Any] = {}
    peer_stats = _peer_stats_for_dir(metrics, dir_path)
    for peer in peers:
        if peer in peer_stats:
            format_peer_status_metrics(
                result, dir_path, peer,
                format_and_order_sync_stat_for_display(peer_stats[peer]))
    return result


def _metrics_for_peer(metrics, peer_uuid):
    result: Dict[str, Any] = {}
    for dir_path, dir_entry in metrics.items():
        peer_stats = dir_entry.get('peer', {})
        if peer_uuid in peer_stats:
            format_peer_status_metrics(
                result, dir_path, peer_uuid,
                format_and_order_sync_stat_for_display(peer_stats[peer_uuid]))
    return result


class SyncStatCompleteCache:
    def __init__(self):
        self._caches = {}

    def _cache_ttl_secs(self):
        return CACHE_TTL_SECS

    def _prune(self, filesystem):
        entry = self._caches.get(filesystem)
        if entry and time.monotonic() >= entry['expires_at']:
            del self._caches[filesystem]

    def try_get(self, filesystem, mirrored_dir_path, peer_uuid, peers):
        self._prune(filesystem)
        complete = self._caches.get(filesystem)
        if not complete:
            return None
        now = time.monotonic()
        if now >= complete['expires_at']:
            return None

        if mirrored_dir_path:
            dir_path = norm_path(mirrored_dir_path)
            if complete['peer_uuid'] is None or complete['peer_uuid'] == peer_uuid:
                if _requested_peers_have_stats(complete['metrics'], peers, dir_path):
                    return metrics_for_dir_and_peers(
                        complete['metrics'], dir_path, peers)
            return None

        if peer_uuid is None:
            if complete['peer_uuid'] is not None:
                return None
            return dict(complete['metrics'])
        if complete['peer_uuid'] not in (None, peer_uuid):
            return None
        return _metrics_for_peer(complete['metrics'], peer_uuid)

    def store(self, filesystem, metrics, peer_uuid):
        self._prune(filesystem)
        self._caches[filesystem] = {
            'metrics': metrics,
            'expires_at': time.monotonic() + self._cache_ttl_secs(),
            'peer_uuid': peer_uuid,
        }
