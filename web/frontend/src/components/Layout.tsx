import { NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: "📊" },
  { to: "/production", label: "Production", icon: "🚀" },
  { to: "/evaluation", label: "Evaluation", icon: "📈" },
  { to: "/portfolio", label: "Portfolio", icon: "💼" },
  { to: "/trade-history", label: "Trade History", icon: "📋" },
  { to: "/signals", label: "Signals", icon: "📡" },
  { to: "/stocks", label: "Stocks", icon: "🔍" },
  { to: "/strategies", label: "Strategies", icon: "🧠" },
];

export default function Layout() {
  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <nav className="w-56 shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <h1 className="text-lg font-bold text-blue-400">J-Stock</h1>
          <p className="text-xs text-gray-500">Dashboard</p>
        </div>
        <ul className="flex-1 py-2 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-2 px-4 py-2 text-sm transition-colors ${
                    isActive
                      ? "bg-blue-600/20 text-blue-400 border-r-2 border-blue-400"
                      : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
                  }`
                }
              >
                <span>{item.icon}</span>
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
