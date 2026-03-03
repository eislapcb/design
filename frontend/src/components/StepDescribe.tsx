"use client";

import type { WizardState, WizardAction } from "@/lib/types";

interface Props {
  state: WizardState;
  dispatch: React.Dispatch<WizardAction>;
  onNext: () => void;
}

export function StepDescribe({ state, dispatch, onNext }: Props) {
  return (
    <div>
      <h2 className="text-2xl font-bold text-teal mb-2">
        What should your board do?
      </h2>
      <p className="text-dark-light mb-6">
        Describe your project in plain English. No technical knowledge
        required — just tell us what you need.
      </p>

      <textarea
        value={state.description}
        onChange={(e) =>
          dispatch({ type: "SET_DESCRIPTION", description: e.target.value })
        }
        placeholder="e.g. I need a board that connects to WiFi, reads temperature and humidity, and runs on a rechargeable battery..."
        rows={6}
        className="w-full px-4 py-3 rounded-lg border border-cream-dark bg-white focus:outline-none focus:ring-2 focus:ring-copper resize-none text-dark"
      />

      {state.error && (
        <div className="mt-4 bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
          {state.error}
        </div>
      )}

      <div className="mt-6 flex justify-end">
        <button
          onClick={onNext}
          disabled={!state.description.trim() || state.loading}
          className="bg-copper hover:bg-copper-light disabled:opacity-50 text-white px-8 py-3 rounded-lg font-medium transition-colors"
        >
          {state.loading ? "Analysing your description..." : "Continue"}
        </button>
      </div>
    </div>
  );
}
