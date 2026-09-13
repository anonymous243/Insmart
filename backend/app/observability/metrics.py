"""
C5 Metrics Collection — In-memory metrics with bounded labels.

Provides:
- Counter metrics
- Histogram metrics (latency)
- Gauge metrics

All metrics use bounded labels only. High-cardinality labels are forbidden.

Exposed via JSON endpoint for operational consumption.
"""
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MetricSample:
    """Single metric observation."""
    timestamp: datetime
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class HistogramBucket:
    """Histogram bucket for latency measurement."""
    le: float  # Upper bound
    count: int = 0
    sum: float = 0.0


class MetricsCollector:
    """
    Thread-safe in-memory metrics collector.
    
    Metrics categories:
    - HTTP requests
    - Claim processing
    - Background jobs
    - External operations
    - Reconciliation
    - HIS callbacks
    - Worker health
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._histograms: Dict[str, Dict[str, List[MetricSample]]] = defaultdict(lambda: defaultdict(list))
        self._gauges: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._start_time = datetime.now(timezone.utc)
    
    def _safe_label_value(self, value: str, max_len: int = 50) -> str:
        """Sanitize label value to prevent high-cardinality injection."""
        if not value:
            return "unknown"
        value = value.strip()
        if len(value) > max_len:
            value = value[:max_len]
        # Replace problematic characters
        value = value.replace(",", "_").replace("=", "_").replace(";", "_")
        return value or "unknown"
    
    def increment_counter(self, metric_name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        with self._lock:
            label_key = self._make_label_key(labels or {})
            self._counters[metric_name][label_key] += value
    
    def record_histogram(self, metric_name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record a histogram observation (e.g., latency)."""
        with self._lock:
            label_key = self._make_label_key(labels or {})
            self._histograms[metric_name][label_key].append(MetricSample(
                timestamp=datetime.now(timezone.utc),
                value=value,
                labels=labels or {},
            ))
            # Keep only last 1000 samples per bucket to prevent memory growth
            if len(self._histograms[metric_name][label_key]) > 1000:
                self._histograms[metric_name][label_key] = self._histograms[metric_name][label_key][-1000:]
    
    def set_gauge(self, metric_name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric value."""
        with self._lock:
            label_key = self._make_label_key(labels or {})
            self._gauges[metric_name][label_key] = value
    
    def get_counter(self, metric_name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current counter value."""
        with self._lock:
            label_key = self._make_label_key(labels or {})
            return self._counters.get(metric_name, {}).get(label_key, 0.0)
    
    def get_histogram_stats(self, metric_name: str, labels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Get histogram statistics (count, sum, min, max, p50, p95, p99)."""
        with self._lock:
            label_key = self._make_label_key(labels or {})
            samples = self._histograms.get(metric_name, {}).get(label_key, [])
            if not samples:
                return {"count": 0, "sum": 0.0, "min": 0.0, "max": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
            
            values = [s.value for s in samples]
            values.sort()
            count = len(values)
            total = sum(values)
            
            def percentile(p: float) -> float:
                idx = int(count * p / 100.0)
                idx = min(idx, count - 1)
                return values[idx]
            
            return {
                "count": count,
                "sum": total,
                "min": values[0],
                "max": values[-1],
                "p50": percentile(50),
                "p95": percentile(95),
                "p99": percentile(99),
            }
    
    def get_gauge(self, metric_name: str, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current gauge value."""
        with self._lock:
            label_key = self._make_label_key(labels or {})
            return self._gauges.get(metric_name, {}).get(label_key, 0.0)
    
    def get_all_metrics(self) -> Dict[str, Any]:
        """Export all metrics for operational endpoints."""
        with self._lock:
            result = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "uptime_seconds": (datetime.now(timezone.utc) - self._start_time).total_seconds(),
                "counters": {},
                "histograms": {},
                "gauges": {},
            }
            
            for metric_name, buckets in self._counters.items():
                result["counters"][metric_name] = dict(buckets)
            
            for metric_name, buckets in self._histograms.items():
                result["histograms"][metric_name] = {
                    label_key: {
                        "count": len(samples),
                        "sum": sum(s.value for s in samples),
                        "min": min(s.value for s in samples) if samples else 0,
                        "max": max(s.value for s in samples) if samples else 0,
                    }
                    for label_key, samples in buckets.items()
                }
            
            for metric_name, buckets in self._gauges.items():
                result["gauges"][metric_name] = dict(buckets)
            
            return result
    
    def _make_label_key(self, labels: Dict[str, str]) -> str:
        """Create deterministic key from labels, filtering high-cardinality values."""
        safe_labels = {}
        for k, v in labels.items():
            if k.lower() in {"transaction_id", "claim_id", "job_id", "correlation_id", "patient_id"}:
                continue  # Skip high-cardinality labels
            safe_labels[k] = self._safe_label_value(v)
        return ",".join(f"{k}={v}" for k, v in sorted(safe_labels.items()))


# Global metrics collector instance
metrics = MetricsCollector()
