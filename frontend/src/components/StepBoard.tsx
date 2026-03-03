"use client";

import type { WizardState, WizardAction } from "@/lib/types";

interface Props {
  state: WizardState;
  dispatch: React.Dispatch<WizardAction>;
  onNext: () => void;
  onBack: () => void;
}

export function StepBoard({ state, dispatch, onNext, onBack }: Props) {
  const { boardConfig } = state;

  const update = (patch: Partial<typeof boardConfig>) =>
    dispatch({ type: "SET_BOARD_CONFIG", config: patch });

  return (
    <div>
      <h2 className="text-2xl font-bold text-teal mb-2">Board size</h2>
      <p className="text-dark-light mb-6">
        Set the dimensions of your PCB. We&apos;ll determine layers, finish,
        and other parameters based on your design requirements.
      </p>

      <div className="grid grid-cols-2 gap-6 max-w-md">
        <div>
          <label className="block text-sm font-medium mb-1">Width (mm)</label>
          <input
            type="number"
            min={10}
            max={300}
            value={boardConfig.width_mm}
            onChange={(e) => update({ width_mm: Number(e.target.value) })}
            className="w-full px-4 py-2 rounded-lg border border-cream-dark bg-white focus:outline-none focus:ring-2 focus:ring-copper"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Height (mm)</label>
          <input
            type="number"
            min={10}
            max={300}
            value={boardConfig.height_mm}
            onChange={(e) => update({ height_mm: Number(e.target.value) })}
            className="w-full px-4 py-2 rounded-lg border border-cream-dark bg-white focus:outline-none focus:ring-2 focus:ring-copper"
          />
        </div>
      </div>

      {/* Show what we've determined */}
      <div className="mt-6 bg-cream/30 rounded-lg p-4 max-w-md">
        <div className="text-xs font-medium text-teal uppercase tracking-wide mb-2">
          Determined by your design
        </div>
        <div className="grid grid-cols-2 gap-3 text-sm text-dark-light">
          <div>
            <span className="text-dark font-medium">Layers:</span>{" "}
            {boardConfig.layers}
          </div>
          <div>
            <span className="text-dark font-medium">Finish:</span>{" "}
            {boardConfig.finish}
          </div>
        </div>
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
          onClick={onNext}
          className="bg-copper hover:bg-copper-light text-white px-8 py-3 rounded-lg font-medium transition-colors"
        >
          Continue
        </button>
      </div>
    </div>
  );
}
