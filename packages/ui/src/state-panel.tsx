import {
  CheckCircle,
  CircleNotch,
  Tray,
  WarningCircle,
  WifiSlash,
} from "@phosphor-icons/react";

export type StatePanelState =
  | "loading"
  | "empty"
  | "error"
  | "offline"
  | "success";

export interface StatePanelProps {
  actionLabel?: string;
  description: string;
  onAction?: () => void;
  state: StatePanelState;
  title: string;
}

const iconByState = {
  loading: CircleNotch,
  empty: Tray,
  error: WarningCircle,
  offline: WifiSlash,
  success: CheckCircle,
} as const;

export function StatePanel({
  actionLabel,
  description,
  onAction,
  state,
  title,
}: StatePanelProps) {
  const Icon = iconByState[state];
  const isAlert = state === "error" || state === "offline";

  return (
    <section
      aria-label={title}
      aria-live={isAlert ? "assertive" : "polite"}
      className={`py-state-panel py-state-panel--${state}`}
      role={isAlert ? "alert" : "status"}
    >
      <span aria-hidden="true" className="py-state-panel__icon">
        <Icon
          className={state === "loading" ? "is-spinning" : undefined}
          size={28}
        />
      </span>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {actionLabel && onAction ? (
        <button
          className="py-button py-button--secondary"
          onClick={onAction}
          type="button"
        >
          {actionLabel}
        </button>
      ) : null}
    </section>
  );
}
