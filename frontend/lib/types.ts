export type ProjectStatus =
  | 'submitted'
  | 'in_design'
  | 'in_review'
  | 'awaiting_approval'
  | 'manufacturing'
  | 'delivered'

export interface Project {
  id: string
  name: string
  description: string
  tier: 1 | 2 | 3
  status: ProjectStatus
  createdAt: string
  updatedAt: string
  price: number
  mcu?: string
}

export interface DesignComponent {
  name: string
  value: string
  quantity: number
}

export interface DesignSummary {
  projectId: string
  boardDimensions: string
  layers: number
  mcu: string
  powerInput: string
  interfaces: string[]
  componentCount: number
  components: DesignComponent[]
  notes: string[]
}

export interface ShippingOption {
  name: string
  price: number
  days: number
}

export interface FabQuote {
  fab: string
  abbr: string
  country: string
  boardCost: number
  assemblyCost: number
  componentsCost: number
  leadTimeDays: number
  shippingOptions: ShippingOption[]
  recommended?: boolean
}
