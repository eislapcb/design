"use client";

import type { WizardStep } from "@/lib/types";

const STEPS: { num: WizardStep; label: string }[] = [
  { num: 1, label: "Describe" },
  { num: 2, label: "Features" },
  { num: 3, label: "Board" },
  { num: 4, label: "Review" },
];

interface WizardShellProps {
  step: WizardStep;
  children: React.ReactNode;
}

export function WizardShell({ step, children }: WizardShellProps) {
  return (
    <div className="max-w-3xl mx-auto px-6 py-10">
      {/* Progress bar */}
      <div className="flex items-center mb-10">
        {STEPS.map(({ num, label }, i) => (
          <div key={num} className="flex items-center flex-1 last:flex-initial">
            <div className="flex flex-col items-center">
              <div
                className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
                  num <= step
                    ? "bg-copper text-white"
                    : "bg-cream-dark text-dark-light"
                }`}
              >
                {num}
              </div>
              <span
                className={`text-xs mt-1 ${num <= step ? "text-teal font-medium" : "text-dark-light"}`}
              >
                {label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div
                className={`flex-1 h-0.5 mx-3 mt-[-1rem] ${
                  num < step ? "bg-copper" : "bg-cream-dark"
                }`}
              />
            )}
          </div>
        ))}
      </div>

      {children}
    </div>
  );
}
