"use client";

import { useEffect, useState } from "react";
import type { WizardState, WizardAction } from "@/lib/types";
import { apiFetch } from "@/lib/api";

interface Capability {
  id: string;
  display_label: string;
  group: string;
}

interface Props {
  state: WizardState;
  dispatch: React.Dispatch<WizardAction>;
  onNext: () => void;
  onBack: () => void;
}

const GROUP_LABELS: Record<string, string> = {
  connectivity: "Connectivity",
  sensing: "Sensors",
  power: "Power",
  output: "Outputs",
  ui: "User Interface",
  storage: "Storage",
};

// Customer-facing capabilities only — processing tier is auto-selected by resolver
const CUSTOMER_CAPS = new Set([
  // Connectivity
  "wifi", "bluetooth", "lora", "zigbee", "ethernet", "cellular_2g", "cellular_4g",
  "gps", "nfc", "ir",
  // Sensors
  "sense_temperature", "sense_humidity", "sense_motion_imu", "sense_proximity",
  "sense_light", "sense_pressure", "sense_gas", "sense_soil_moisture",
  "sense_current", "sense_sound", "sense_water_level", "sense_water_flow",
  // Power
  "power_usb", "power_lipo", "power_aa", "power_solar", "power_mains",
  // Output
  "motor_dc", "motor_stepper", "motor_servo", "relay",
  "led_single", "led_rgb_strip", "buzzer", "speaker",
  // UI
  "display_oled", "display_lcd", "display_tft", "buttons", "touch",
  "rotary_encoder",
  // Storage
  "storage_sd", "rtc",
]);

export function StepCapabilities({
  state,
  dispatch,
  onNext,
  onBack,
}: Props) {
  const [allCaps, setAllCaps] = useState<Capability[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetch("/data/capabilities.json")
      .then((r) => r.json())
      .then((data) => {
        const caps = (data.capabilities || []).filter(
          (c: Capability) => CUSTOMER_CAPS.has(c.id)
        );
        setAllCaps(caps);
      })
      .catch(() => {});
  }, []);

  // Initialise selected from resolved capabilities
  useEffect(() => {
    if (state.resolved?.capabilities) {
      setSelected(new Set(state.resolved.capabilities.filter(c => CUSTOMER_CAPS.has(c))));
    } else if (state.intent?.capabilities) {
      setSelected(new Set(state.intent.capabilities.filter(c => CUSTOMER_CAPS.has(c))));
    }
  }, [state.resolved, state.intent]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleNext = async () => {
    dispatch({ type: "SET_LOADING", loading: true });
    dispatch({ type: "SET_ERROR", error: null });
    try {
      const caps = Array.from(selected);
      const resolveRes = await apiFetch<{
        resolved_components: any[];
        warnings: any[];
        recommended_layers: number;
        mcu: any;
        pricing: any;
        error?: string;
      }>("/api/resolve", {
        method: "POST",
        body: JSON.stringify({
          capabilities: caps,
          board: {
            layers: state.boardConfig.layers,
            dimensions_mm: [
              state.boardConfig.width_mm,
              state.boardConfig.height_mm,
            ],
          },
        }),
      });

      if (resolveRes.error) {
        throw new Error(resolveRes.error);
      }

      const resolved = {
        components: (resolveRes.resolved_components || []).map((c: any) => ({
          ref: c.component_id,
          component_id: c.component_id,
          value: c.display_name,
          reason: c.satisfies?.join(", "),
        })),
        board: {
          width_mm: state.boardConfig.width_mm,
          height_mm: state.boardConfig.height_mm,
          layers: resolveRes.recommended_layers ?? 4,
          finish: "ENIG",
        },
        tier: resolveRes.pricing?.tier ?? 1,
        price_pence: Math.round((resolveRes.pricing?.design_fee_gbp ?? 499) * 100),
        capabilities: caps,
        warnings: resolveRes.warnings,
        mcu: resolveRes.mcu,
      };

      dispatch({ type: "SET_RESOLVED", resolved: resolved as any });
      onNext();
    } catch (err) {
      dispatch({
        type: "SET_ERROR",
        error: err instanceof Error ? err.message : "Failed to resolve design",
      });
    } finally {
      dispatch({ type: "SET_LOADING", loading: false });
    }
  };

  // Group capabilities
  const groups = new Map<string, Capability[]>();
  for (const cap of allCaps) {
    const g = groups.get(cap.group) || [];
    g.push(cap);
    groups.set(cap.group, g);
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-teal mb-2">
        Choose your features
      </h2>
      <p className="text-dark-light mb-6">
        We&apos;ve suggested features based on your description. Add or remove
        anything you need.
      </p>

      <div className="space-y-6">
        {Array.from(groups.entries()).map(([group, caps]) => (
          <div key={group}>
            <h3 className="text-sm font-semibold text-teal uppercase tracking-wide mb-2">
              {GROUP_LABELS[group] || group}
            </h3>
            <div className="flex flex-wrap gap-2">
              {caps.map((cap) => (
                <button
                  key={cap.id}
                  onClick={() => toggle(cap.id)}
                  className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                    selected.has(cap.id)
                      ? "bg-copper text-white border-copper"
                      : "bg-white text-dark border-cream-dark hover:border-copper"
                  }`}
                >
                  {cap.display_label}
                </button>
              ))}
            </div>
          </div>
        ))}
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
          onClick={handleNext}
          disabled={selected.size === 0 || state.loading}
          className="bg-copper hover:bg-copper-light disabled:opacity-50 text-white px-8 py-3 rounded-lg font-medium transition-colors"
        >
          {state.loading ? "Resolving design..." : "Continue"}
        </button>
      </div>
    </div>
  );
}
