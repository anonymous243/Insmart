import React from 'react';

interface StatusBadgeProps {
  value: string;
  showDot?: boolean;
}

const STATUS_MAP: Record<string, string> = {
  // Transaction statuses
  'ADJUDICATED_APPROVED': 'approved',
  'ADJUDICATED_REVIEW': 'review',
  'ADJUDICATED_REJECTED': 'rejected',
  'VALIDATION_FAILED': 'rejected',
  'TPA_ERROR': 'rejected',
  'RECEIVED': 'info',
  // FWA results
  'PASS': 'pass',
  'FWA_FLAG': 'fwa_flag',
  'FWA_REVIEW': 'fwa_review',
  'PRICE_FLAG': 'price_flag',
  // Adjudication status
  'APPROVED': 'approved',
  'REVIEW': 'review',
  'REJECTED': 'rejected',
  // Delivery
  'DELIVERED': 'delivered',
  'PENDING': 'pending',
  'FAILED': 'failed',
  // Mapping
  'MAPPED': 'mapped',
  'UNMAPPED': 'unmapped',
  // Benchmark
  'NO_BENCHMARK': 'no_benchmark',
  // Hospital
  'ACTIVE': 'active',
};

const LABELS: Record<string, string> = {
  'ADJUDICATED_APPROVED': 'Approved',
  'ADJUDICATED_REVIEW': 'Under Review',
  'ADJUDICATED_REJECTED': 'Rejected',
  'VALIDATION_FAILED': 'Validation Failed',
  'TPA_ERROR': 'TPA Error',
  'PRICE_FLAG': 'Price Flag',
  'FWA_FLAG': 'FWA Flagged',
  'FWA_REVIEW': 'FWA Review',
  'NO_BENCHMARK': 'No Benchmark',
  'DELIVERED': 'Delivered',
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({ value, showDot = true }) => {
  const cls = STATUS_MAP[value?.toUpperCase()] || STATUS_MAP[value] || 'info';
  const label = LABELS[value?.toUpperCase()] || LABELS[value] || value;
  return (
    <span className={`badge badge-${cls}`}>
      {showDot && <span className="badge-dot" />}
      {label}
    </span>
  );
};
