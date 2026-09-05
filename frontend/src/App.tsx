import { FileText, Server } from "lucide-react";
import { useEffect, useState } from "react";

import "./App.css";
import { getHealth } from "./lib/api";

type ApiStatus = "checking" | "online" | "offline";

function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");

  useEffect(() => {
    getHealth()
      .then(() => setApiStatus("online"))
      .catch(() => setApiStatus("offline"));
  }, []);

  return (
    <main className="app-shell">
      <section className="workspace">
        <header className="topbar">
          <div className="brand">
            <FileText aria-hidden="true" size={24} />
            <span>Ylookup PDF Analyzer</span>
          </div>
          <div className={`status-pill status-${apiStatus}`}>
            <Server aria-hidden="true" size={16} />
            <span>API {apiStatus}</span>
          </div>
        </header>

        <section className="panel">
          <div>
            <p className="eyebrow">Initial workspace</p>
            <h1>Upload, inspect, and analyze PDFs from one focused interface.</h1>
            <p className="lede">
              The FastAPI backend is wired to this React client and ready for upload,
              extraction, and analysis routes.
            </p>
          </div>

          <div className="dropzone">
            <FileText aria-hidden="true" size={48} />
            <strong>PDF upload area</strong>
            <span>Connect this to the next backend endpoint.</span>
          </div>
        </section>
      </section>
    </main>
  );
}

export default App;

