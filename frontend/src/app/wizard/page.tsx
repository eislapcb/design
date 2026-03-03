"use client";

import { useReducer } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { WizardShell } from "@/components/WizardShell";
import { StepDescribe } from "@/components/StepDescribe";
import { StepCapabilities } from "@/components/StepCapabilities";
import { StepBoard } from "@/components/StepBoard";
import { StepReview } from "@/components/StepReview";
import type { WizardState, WizardAction } from "@/lib/types";

const INITIAL_STATE: WizardState = {
  step: 1,
  description: "",
  intent: null,
  resolved: null,
  boardConfig: { width_mm: 50, height_mm: 50, layers: 2, finish: "HASL" },
  loading: false,
  error: null,
};

function reducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case "SET_STEP":
      return { ...state, step: action.step, error: null };
    case "SET_DESCRIPTION":
      return { ...state, description: action.description };
    case "SET_INTENT":
      return { ...state, intent: action.intent };
    case "SET_RESOLVED": {
      const r = action.resolved;
      if (!r) return state;
      return {
        ...state,
        resolved: r,
        boardConfig: {
          width_mm: r.board?.width_mm ?? state.boardConfig.width_mm,
          height_mm: r.board?.height_mm ?? state.boardConfig.height_mm,
          layers: r.board?.layers ?? state.boardConfig.layers,
          finish: r.board?.finish ?? state.boardConfig.finish,
        },
      };
    }
    case "SET_BOARD_CONFIG":
      return {
        ...state,
        boardConfig: { ...state.boardConfig, ...action.config },
      };
    case "SET_LOADING":
      return { ...state, loading: action.loading };
    case "SET_ERROR":
      return { ...state, error: action.error };
    case "RESET":
      return INITIAL_STATE;
    default:
      return state;
  }
}

export default function WizardPage() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  if (authLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-dark-light">
        Loading...
      </div>
    );
  }

  if (!user) {
    router.push("/login");
    return null;
  }

  const handleDescribeNext = async () => {
    dispatch({ type: "SET_LOADING", loading: true });
    dispatch({ type: "SET_ERROR", error: null });
    try {
      // Step 1: parse intent
      const intentRes = await apiFetch<{
        success: boolean;
        result: { capabilities: string[]; suggested_board?: Record<string, unknown> };
        error?: string;
      }>("/api/parse-intent", {
        method: "POST",
        body: JSON.stringify({ description: state.description }),
      });

      if (!intentRes.success) {
        throw new Error(intentRes.error || "Failed to understand description");
      }

      dispatch({
        type: "SET_INTENT",
        intent: {
          description: state.description,
          capabilities: intentRes.result.capabilities,
        },
      });

      // Step 2: resolve design
      const suggestedBoard = intentRes.result.suggested_board || {};
      const resolveRes = await apiFetch<{
        resolved_components: any[];
        warnings: any[];
        power_budget: any;
        recommended_layers: number;
        mcu: any;
        pricing: any;
        error?: string;
      }>("/api/resolve", {
        method: "POST",
        body: JSON.stringify({
          capabilities: intentRes.result.capabilities,
          board: suggestedBoard,
        }),
      });

      if (resolveRes.error) {
        throw new Error(resolveRes.error);
      }

      // Map API response to ResolvedDesign shape
      const dims = suggestedBoard.dimensions_mm as number[] | undefined;
      const resolved = {
        components: (resolveRes.resolved_components || []).map((c: any) => ({
          ref: c.component_id,
          component_id: c.component_id,
          value: c.display_name,
          reason: c.satisfies?.join(", "),
        })),
        board: {
          width_mm: dims?.[0] ?? 50,
          height_mm: dims?.[1] ?? 50,
          layers: resolveRes.recommended_layers ?? 4,
          finish: "ENIG",
        },
        tier: resolveRes.pricing?.tier ?? 1,
        price_pence: Math.round((resolveRes.pricing?.design_fee_gbp ?? 499) * 100),
        capabilities: intentRes.result.capabilities,
        warnings: resolveRes.warnings,
        mcu: resolveRes.mcu,
      };
      dispatch({ type: "SET_RESOLVED", resolved });
      dispatch({ type: "SET_STEP", step: 2 });
    } catch (err) {
      dispatch({
        type: "SET_ERROR",
        error:
          err instanceof Error ? err.message : "Something went wrong",
      });
    } finally {
      dispatch({ type: "SET_LOADING", loading: false });
    }
  };

  return (
    <WizardShell step={state.step}>
      {state.step === 1 && (
        <StepDescribe
          state={state}
          dispatch={dispatch}
          onNext={handleDescribeNext}
        />
      )}
      {state.step === 2 && (
        <StepCapabilities
          state={state}
          dispatch={dispatch}
          onNext={() => dispatch({ type: "SET_STEP", step: 3 })}
          onBack={() => dispatch({ type: "SET_STEP", step: 1 })}
        />
      )}
      {state.step === 3 && (
        <StepBoard
          state={state}
          dispatch={dispatch}
          onNext={() => dispatch({ type: "SET_STEP", step: 4 })}
          onBack={() => dispatch({ type: "SET_STEP", step: 2 })}
        />
      )}
      {state.step === 4 && (
        <StepReview
          state={state}
          dispatch={dispatch}
          onBack={() => dispatch({ type: "SET_STEP", step: 3 })}
        />
      )}
    </WizardShell>
  );
}
