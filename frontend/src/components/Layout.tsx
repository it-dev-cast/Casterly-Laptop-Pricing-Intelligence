import { NavLink, Outlet } from "react-router-dom";
import { useApp } from "../context";
import { Icon } from "./Icons";

const NAV = [
  { sec: "Pricing Intelligence", perm: "pi_view" },
  { to: "/pi", label: "Dashboard", icon: Icon.dashboard, end: true, perm: "pi_view" },
  { to: "/pi/new", label: "New market valuation", icon: Icon.plus, perm: "pi_import" },
  { to: "/pi/import", label: "Excel bulk import", icon: Icon.upload, perm: "pi_import" },
  { to: "/pi/research", label: "Market research results", icon: Icon.search, perm: "pi_view" },
  { to: "/pi/review", label: "Asset pricing review", icon: Icon.tag, perm: "pi_view" },
  { to: "/pi/quotations", label: "Vendor quotations", icon: Icon.doc, perm: "pi_view" },
  { to: "/pi/history", label: "Price history", icon: Icon.history, perm: "pi_view" },
  { to: "/pi/sources", label: "Market source library", icon: Icon.market, perm: "pi_view" },
  { to: "/pi/rules", label: "Pricing rules", icon: Icon.settings, perm: "pi_view" },
  { to: "/pi/exceptions", label: "Review exceptions", icon: Icon.alert, perm: "pi_view" },
  { to: "/pi/reports", label: "Valuation reports", icon: Icon.download, perm: "pi_view" },
  { sec: "Decide" },
  { to: "/", label: "Dashboard", icon: Icon.dashboard, end: true },
  { to: "/inventory", label: "Inventory & lots", icon: Icon.laptop },
  { to: "/evidence", label: "Market evidence", icon: Icon.market },
  { sec: "Operate" },
  { to: "/import", label: "Upload & review", icon: Icon.upload },
  { to: "/outcomes", label: "Transaction outcomes", icon: Icon.outcome },
  { to: "/settings", label: "Cost & margin settings", icon: Icon.settings },
  { sec: "Assure" },
  { to: "/validation", label: "Validation", icon: Icon.check },
  { to: "/connectors", label: "Connectors", icon: Icon.plug },
  { to: "/admin", label: "Users & audit", icon: Icon.shield, perm: "view_audit" },
] as const;

export default function Layout() {
  const { user, logout, view, setView, can } = useApp();
  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brandmark">
          <div className="logo"><img src="/brand/casterly-mark.png" alt="" /></div>
          <div>
            <div className="t1">CASTERLY</div>
            <div className="t2">Laptop Pricing Intelligence</div>
          </div>
        </div>
        {NAV.map((n, i) =>
          "sec" in n ? ("perm" in n && !can(n.perm) ? null :
            <div className="navsec" key={i}>
              {n.sec}
            </div>
          ) : "perm" in n && n.perm && !can(n.perm) ? null : (
            <NavLink key={n.to} to={n.to} end={"end" in n} className={({ isActive }) => `navlink ${isActive ? "active" : ""}`}>
              <n.icon />
              {n.label}
            </NavLink>
          ),
        )}
        <div className="foot">
          <div className="who">{user?.name}</div>
          <div style={{ textTransform: "capitalize" }}>{user?.role}</div>
          <button className="btn sm" style={{ marginTop: 8 }} onClick={logout}>
            Sign out
          </button>
        </div>
      </nav>
      <div className="main">
        <div className="topbar">
          <span className="muted small">Data shown</span>
          <div className="viewswitch" role="group" aria-label="Dataset">
            <button className={view === "real" ? "on" : ""} onClick={() => setView("real")}>
              Real evidence
            </button>
            <button className={view === "demo" ? "on demo" : ""} onClick={() => setView("demo")}>
              Synthetic demo
            </button>
          </div>
          <div className="spacer" />
          <span className="muted small">All prices INR · selling prices include GST unless marked ex-GST</span>
        </div>
        {view === "demo" && (
          <div className="content" style={{ paddingBottom: 0 }}>
            <div className="banner demo">
              <b>Synthetic demo view.</b> Every record here is generated sample data, not market evidence. It is
              stored separately and never used to value real inventory.
            </div>
          </div>
        )}
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
