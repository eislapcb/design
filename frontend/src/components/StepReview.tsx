"use client";

import { useRouter } from "next/navigation";
import type { WizardState, WizardAction } from "@/lib/types";
import { apiFetch } from "@/lib/api";

interface Props {
  state: WizardState;
  dispatch: React.Dispatch<WizardAction>;
  onBack: () => void;
}

const TIER_NAMES: Record<number, string> = {
  1: "Standard",
  2: "Advanced",
  3: "Complex",
};

export function StepReview({ state, dispatch, onBack }: Props) {
  const { resolved, boardConfig } = state;
  const router = useRouter();
  const tier = resolved?.tier ?? 1;
  const pricePence = resolved?.price_pence ?? 49900;
  const priceStr = `£${(pricePence / 100).toFixed(2)}`;

  const handlePay = async () => {
    dispatch({ type: "SET_LOADING", loading: true });
    dispatch({ type: "SET_ERROR", error: null });
    try {
      const res = await apiFetch<{
        success: boolean;
        url?: string;
        designId?: string;
      }>("/api/checkout", {
        method: "POST",
        body: JSON.stringify({
          tier,
          boardConfig,
          capabilities: resolved?.capabilities || [],
        }),
      });
      if (res.url) {
        window.location.href = res.url;
      } else if (res.designId) {
        // Dev mode — no Stripe, go straight to dashboard
        router.push(`/jobs/${res.designId}`);
      }
    } catch (err) {
      dispatch({
        type: "SET_ERROR",
        error: err instanceof Error ? err.message : "Payment failed",
      });
    } finally {
      dispatch({ type: "SET_LOADING", loading: false });
    }
  };

  const components = resolved?.components || [];
  const warnings = (resolved as any)?.warnings || [];

  return (
    <div>
      <h2 className="text-2xl font-bold text-teal mb-2">Review your design</h2>
      <p className="text-dark-light mb-6">
        Here&apos;s a summary of what we&apos;ll build for you.
      </p>

      <div className="bg-white rounded-xl p-6 shadow-sm space-y-4">
        <div className="flex justify-between items-center pb-4 border-b border-cream-dark">
          <div>
            <div className="text-sm text-dark-light">Design tier</div>
            <div className="font-semibold text-teal">
              {TIER_NAMES[tier] || `Tier ${tier}`}
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm text-dark-light">Design fee</div>
            <div className="text-2xl font-bold text-copper">{priceStr}</div>
          </div>
        </div>

        <div>
          <div className="text-sm font-medium text-teal mb-2">Board</div>
          <div className="text-sm text-dark-light">
            {boardConfig.width_mm} &times; {boardConfig.height_mm} mm,{" "}
            {boardConfig.layers} layers, {boardConfig.finish} finish
          </div>
        </div>

        <div>
          <div className="text-sm font-medium text-teal mb-2">
            Components ({components.length})
          </div>
          <div className="grid grid-cols-2 gap-1 text-sm text-dark-light">
            {components.map((c) => (
              <div key={c.ref}>
                <span className="font-mono text-xs text-copper">{c.ref}</span>{" "}
                {c.value || c.component_id}
              </div>
            ))}
          </div>
        </div>

        {/* Warnings from resolver */}
        {warnings.length > 0 && (
          <div>
            <div className="text-sm font-medium text-teal mb-2">Notes</div>
            <ul className="text-xs text-dark-light space-y-1">
              {warnings.map((w: any, i: number) => (
                <li key={i} className={`flex gap-1 ${w.level === "warn" ? "text-amber-600" : ""}`}>
                  <span>{w.level === "warn" ? "⚠" : "ℹ"}</span>
                  {w.message}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {state.error && (
        <div className="mt-4 bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
          {state.error}
        </div>
      )}

      <div className="mt-8 flex justify-between">
        <button
          onClick={onBack}
          className="text-teal hover:text-copper transition-colors font-medium"
        >
          Back
        </button>
        <button
          onClick={handlePay}
          disabled={state.loading}
          className="bg-copper hover:bg-copper-light disabled:opacity-50 text-white px-8 py-3 rounded-lg font-medium transition-colors"
        >
          {state.loading ? "Processing..." : `Pay ${priceStr} & start`}
        </button>
      </div>
    </div>
  );
}
