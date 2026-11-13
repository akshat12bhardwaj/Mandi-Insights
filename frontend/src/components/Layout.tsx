import { LayoutDashboard, Menu, Store, Warehouse, X } from "lucide-react";
import { createContext, Suspense, useContext, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { type Crop } from "../lib/api";
import { cn } from "../lib/format";
import { Card } from "./ui";

export const NAV = [
  { to: "/", label: "Strategies", icon: LayoutDashboard },
  { to: "/markets", label: "Markets", icon: Store },
  { to: "/warehouses", label: "Warehouses", icon: Warehouse },
];

const CropCtx = createContext<{ crop: Crop; setCrop: (c: Crop) => void }>({ crop: "Onion", setCrop: () => {} });
export const useCrop = () => useContext(CropCtx);

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 rounded-lg" aria-label="Mandi Insights home">
      <span className="grid size-9 place-items-center rounded-lg bg-ok text-white">
        <svg viewBox="0 0 32 32" width="20" height="20" aria-hidden><path d="M16 25V13m0 0c0-4 3-6 7-6 0 4-3 6-7 6Zm0 4c0-3-2.5-5-6-5 0 3 2.5 5 6 5Z" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold text-ink">Mandi Insights</span>
        <span className="block text-[11.5px] text-muted">From harvest to market</span>
      </span>
    </Link>
  );
}

export function Layout() {
  const [crop, setCrop] = useState<Crop>("Onion");
  const [open, setOpen] = useState(false);
  return (
    <CropCtx.Provider value={{ crop, setCrop }}>
      <div className="min-h-full bg-canvas">
        <aside className="sticky top-0 z-[700] border-b border-line bg-white lg:fixed lg:inset-y-0 lg:left-0 lg:flex lg:w-60 lg:flex-col lg:border-r lg:border-b-0">
          <div className="flex h-16 items-center justify-between gap-3 px-4 lg:h-auto lg:px-5 lg:pt-6 lg:pb-5">
            <Logo />
            <button type="button" className="grid size-10 place-items-center rounded-lg border border-line text-ink lg:hidden" onClick={() => setOpen(!open)}
              aria-expanded={open} aria-controls="main-nav" aria-label={open ? "Close menu" : "Open menu"}>
              {open ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
          <div id="main-nav" className={cn("flex-1 flex-col gap-4 px-3 pb-4 lg:flex", open ? "flex" : "hidden")}>
            <nav aria-label="Main">
              <ul className="space-y-0.5">
                {NAV.map(({ to, label, icon: Icon }) => (
                  <li key={to}>
                    <NavLink to={to} end={to === "/"} onClick={() => setOpen(false)}
                      className={({ isActive }) => cn("flex h-10 items-center gap-3 rounded-lg px-3 text-[14px] font-medium transition",
                        isActive ? "bg-ok-soft text-ok" : "text-ink/75 hover:bg-subtle hover:text-ink")}>
                      <Icon size={17} aria-hidden />{label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </nav>
          </div>
        </aside>
        <div className="lg:pl-60"><main className="mx-auto max-w-[1440px] px-4 pb-10 sm:px-6 lg:px-8"><Suspense fallback={<p role="status" className="p-6 text-muted">Loading page…</p>}><Outlet /></Suspense></main></div>
      </div>
    </CropCtx.Provider>
  );
}

export function PageHeader({ icon, title, subtitle, kpis, controls }: { icon?: ReactNode; title: string; subtitle: ReactNode; kpis?: ReactNode; controls?: ReactNode }) {
  return (
    <section className="pt-6 pb-5">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 items-center gap-3">
          {icon && <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-ok-soft text-ok" aria-hidden>{icon}</span>}
          <div className="min-w-0">
            <h1 className="text-[22px] leading-tight font-semibold tracking-tight text-ink sm:text-[24px]">{title}</h1>
            <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>
          </div>
        </div>
        {controls && <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">{controls}</div>}
      </div>
      {kpis && <Card className="mt-4 flex flex-wrap gap-x-10 gap-y-4 px-5 py-4">{kpis}</Card>}
    </section>
  );
}

/** Section heading inside a page: title, one-line explanation, optional right-hand actions. */
export function SectionTitle({ title, hint, actions, id }: { title: string; hint?: ReactNode; actions?: ReactNode; id?: string }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 id={id} className="text-[16px] font-semibold text-ink">{title}</h2>
        {hint && <p className="mt-0.5 text-[12.5px] text-muted">{hint}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/**
 * Map-led workspace: a full-bleed map with a list panel on the left, an optional floating card, and two cards along
 * the bottom. Below 1024px it stacks: panel, map, cards.
 */
export function Workspace({ map, panel, floating, bottom }: { map: ReactNode; panel: ReactNode; floating?: ReactNode; bottom?: ReactNode }) {
  return (
    <section className="flex flex-col gap-4 lg:relative lg:block lg:h-[max(640px,calc(100vh-150px))] lg:overflow-hidden lg:rounded-2xl lg:border lg:border-line lg:bg-subtle">
      <div className="order-2 h-[380px] overflow-hidden rounded-2xl border border-line lg:absolute lg:inset-0 lg:h-auto lg:rounded-none lg:border-0">{map}</div>
      <div className="order-1 lg:absolute lg:top-4 lg:bottom-4 lg:left-4 lg:z-[600] lg:w-[340px]">{panel}</div>
      {floating && <div className="order-3 lg:absolute lg:top-4 lg:right-20 lg:z-[600] lg:w-[300px]">{floating}</div>}
      {bottom && <div className="order-4 grid gap-4 md:grid-cols-2 lg:absolute lg:right-4 lg:bottom-4 lg:left-[372px] lg:z-[600] lg:h-[250px]">{bottom}</div>}
    </section>
  );
}
