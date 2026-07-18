import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";

export interface PageTransitionProps {
  children: ReactNode;
  className?: string;
  reducedMotion?: boolean;
}

export function PageTransition({
  children,
  className,
  reducedMotion,
}: PageTransitionProps) {
  const prefersReducedMotion = useReducedMotion();
  const shouldReduce = reducedMotion ?? Boolean(prefersReducedMotion);
  const duration = shouldReduce ? 0 : 0.2;

  return (
    <motion.div
      animate={{ opacity: 1, y: 0 }}
      className={className}
      data-transition-duration={String(duration)}
      initial={shouldReduce ? false : { opacity: 0, y: 8 }}
      transition={{ duration, ease: [0.2, 0.8, 0.2, 1] }}
    >
      {children}
    </motion.div>
  );
}

export interface SkeletonProps {
  label: string;
  lines?: number;
}

export function Skeleton({ label, lines = 3 }: SkeletonProps) {
  return (
    <div
      aria-label={label}
      aria-live="polite"
      className="py-skeleton"
      role="status"
    >
      <span className="sr-only">{label}</span>
      <span aria-hidden="true" className="py-skeleton__body">
        {Array.from({ length: lines }, (_, index) => (
          <span
            className="py-skeleton__line"
            data-testid="skeleton-line"
            key={index}
            style={{ width: `${Math.max(48, 100 - index * 14)}%` }}
          />
        ))}
      </span>
    </div>
  );
}
