export interface NavItem {
  label: string; href?: string; icon: string
  children?: NavItem[]; badge?: string; badgeColor?: string
}
export const navigation: NavItem[] = [
  { label:'Dashboard', href:'/dashboard', icon:'LayoutDashboard' },
  { label:'CRM', icon:'Users', children:[
    { label:'Leads',    href:'/crm/leads',    icon:'UserPlus' },
    { label:'Clients',  href:'/crm/clients',  icon:'Building2' },
    { label:'Follow-ups', href:'/crm/followups', icon:'CalendarClock' },
    { label:'Contacts', href:'/crm/contacts', icon:'Contact'   },
  ]},
  { label:'Projects', icon:'Briefcase', children:[
    { label:'All Projects', href:'/projects',           icon:'Grid3x3'    },
    { label:'Active',       href:'/projects/active',    icon:'Play' },
    { label:'Completed',    href:'/projects/completed', icon:'CheckCircle2' },
    { label:'Archived',     href:'/projects/archived',  icon:'Archive'    },
  ]},
  { label:'Site Survey', icon:'Ruler', children:[
    { label:'Surveys',      href:'/survey',              icon:'ClipboardList' },
    { label:'Rooms',        href:'/survey/rooms',        icon:'LayoutPanelLeft' },
    { label:'Measurements', href:'/survey/measurements', icon:'Ruler'     },
    { label:'Photos',       href:'/survey/photos',       icon:'Camera'    },
    { label:'Documents',    href:'/survey/documents',    icon:'FileText'  },
  ]},
  { label:'Design Studio', icon:'Palette', children:[
    { label:'AI Designer',  href:'/design/ai',        icon:'Sparkles',  badge:'AI',    badgeColor:'blue'  },
    { label:'3D Editor',    href:'/design/3d',        icon:'Box'        },
    { label:'Renders',      href:'/design/renders',   icon:'Image'      },
    { label:'Floor Plans',  href:'/design/plans',     icon:'Map'        },
    { label:'Elevations',   href:'/design/elevations',icon:'PanelTopOpen' },
    { label:'Ceiling',      href:'/design/ceiling',   icon:'Layers2'    },
    { label:'Electrical',   href:'/design/electrical',icon:'Zap'        },
    { label:'CAD Export',   href:'/design/cad',       icon:'PenTool'    },
    { label:'Versions',     href:'/design/versions',  icon:'GitBranch'  },
  ]},
  { label:'Catalogue', icon:'Package', children:[
    { label:'Furniture',   href:'/catalogue/furniture',  icon:'Sofa'      },
    { label:'Materials',   href:'/catalogue/materials',  icon:'Layers3'   },
    { label:'Lighting',    href:'/catalogue/lighting',   icon:'Lightbulb' },
    { label:'Hardware',    href:'/catalogue/hardware',   icon:'Settings2' },
    { label:'Suppliers',   href:'/catalogue/suppliers',  icon:'Truck'     },
  ]},
  { label:'Estimation', icon:'Calculator', children:[
    { label:'BOQ',        href:'/estimation/boq',        icon:'List'          },
    { label:'Take-off',   href:'/estimation/takeoff',    icon:'Ruler'         },
    { label:'Costing',    href:'/estimation/costing',    icon:'IndianRupee'   },
    { label:'Quotations', href:'/estimation/quotations', icon:'FileSpreadsheet' },
    { label:'Invoices',   href:'/estimation/invoices',   icon:'Receipt' },
  ]},
  { label:'Execution', icon:'Wrench', children:[
    { label:'Procurement',   href:'/execution/procurement',   icon:'ShoppingCart' },
    { label:'Purchase Orders',href:'/execution/po',           icon:'FileCheck'    },
    { label:'Inventory',     href:'/execution/inventory',     icon:'Warehouse'    },
    { label:'Manufacturing', href:'/execution/manufacturing', icon:'Factory'      },
    { label:'Cutting Lists', href:'/execution/cutting',       icon:'Scissors'     },
    { label:'Delivery',      href:'/execution/delivery',      icon:'PackageCheck' },
    { label:'Installation',  href:'/execution/installation',  icon:'HardHat'      },
    { label:'Quality Control',href:'/execution/qc',           icon:'ShieldCheck'  },
  ]},
  { label:'Finance', icon:'Landmark', children:[
    { label:'Payables', href:'/finance/payables', icon:'HandCoins' },
    { label:'Accounting export', href:'/finance/accounting-export', icon:'FileSpreadsheet' },
  ]},
  { label:'Client Portal', href:'/client-portal', icon:'Globe' },
  { label:'Reports', icon:'BarChart3', children:[
    { label:'Revenue',      href:'/reports/revenue',  icon:'TrendingUp'  },
    { label:'Profitability', href:'/reports/profitability', icon:'PiggyBank' },
    { label:'Projects',     href:'/reports/projects', icon:'PieChart'    },
    { label:'AI Analytics', href:'/reports/ai',       icon:'Brain',      badge:'AI', badgeColor:'blue' },
  ]},
  { label:'Settings', icon:'Settings', children:[
    { label:'Company',      href:'/settings/company',  icon:'Building'  },
    { label:'Notifications', href:'/settings/notifications', icon:'Bell' },
    { label:'Users',        href:'/settings/users',    icon:'UserCog'   },
    { label:'Roles',        href:'/settings/roles',    icon:'Shield'    },
    { label:'AI Providers', href:'/settings/ai',       icon:'Cpu',      badge:'Local', badgeColor:'green' },
    { label:'System',       href:'/settings/system',   icon:'Terminal'  },
    { label:'Backups',      href:'/settings/backups',  icon:'DatabaseBackup' },
  ]},
]
