export interface User {
  id: string;
  email: string;
  name?: string;
}

export interface ParsedIntent {
  description: string;
  capabilities: string[];
  board?: {
    width_mm?: number;
    height_mm?: number;
    layers?: number;
  };
}

export interface ResolvedComponent {
  ref: string;
  component_id: string;
  value?: string;
  footprint?: string;
  reason?: string;
}

export interface ResolvedDesign {
  components: ResolvedComponent[];
  board: {
    width_mm: number;
    height_mm: number;
    layers: number;
    finish?: string;
  };
  tier: number;
  price_pence: number;
  capabilities: string[];
  warnings?: { level: string; message: string }[];
  mcu?: { id: string; display_name: string; tier: number } | null;
}

export interface BoardConfig {
  width_mm: number;
  height_mm: number;
  layers: number;
  finish: string;
}

export interface Design {
  id: string;
  customer_id: string;
  description: string;
  status: string;
  tier: number;
  design_fee_gbp: number;
  created_at: string;
  updated_at: string;
  resolved?: ResolvedDesign;
}

export type WizardStep = 1 | 2 | 3 | 4;

export interface WizardState {
  step: WizardStep;
  description: string;
  intent: ParsedIntent | null;
  resolved: ResolvedDesign | null;
  boardConfig: BoardConfig;
  loading: boolean;
  error: string | null;
}

export type WizardAction =
  | { type: "SET_STEP"; step: WizardStep }
  | { type: "SET_DESCRIPTION"; description: string }
  | { type: "SET_INTENT"; intent: ParsedIntent }
  | { type: "SET_RESOLVED"; resolved: ResolvedDesign }
  | { type: "SET_BOARD_CONFIG"; config: Partial<BoardConfig> }
  | { type: "SET_LOADING"; loading: boolean }
  | { type: "SET_ERROR"; error: string | null }
  | { type: "RESET" };
