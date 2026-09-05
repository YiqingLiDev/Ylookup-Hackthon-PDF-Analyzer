import { FileText, Server } from "lucide-react";
import { useEffect, useState } from "react";

import "./App.css";
import { getHealth, processStatements } from "./lib/api";

type ApiStatus = "checking" | "online" | "offline";

function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [files, setFiles] = useState<File[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth()
      .then(() => setApiStatus("online"))
      .catch(() => setApiStatus("offline"));
  }, []);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setFiles(Array.from(event.target.files ?? []));
    setError(null);
  };

  const handleRun = async () => {
    if (files.length === 0) return;

    setIsProcessing(true);
    setError(null);

    try {
      const blob = await processStatements(files);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "sourceline-output.xlsx";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <main className="app-shell">
      <section className="workspace">
        <header className="topbar">
          <div className="brand">
            <FileText aria-hidden="true" size={24} />
            <span>Sourceline</span>
          </div>
          <div className={`status-pill status-${apiStatus}`}>
            <Server aria-hidden="true" size={16} />
            <span>API {apiStatus}</span>
          </div>
        </header>

        <section className="panel">
          <div>
            <p className="eyebrow">Bank statement matching</p>
            <h1>Upload statements, review every match, download the workbook.</h1>
            <p className="lede">
              Every transaction narrative is matched against your master lists by AI, then
              paired with a confidence score and a screenshot of its source page so an
              analyst can verify it before trusting it.
            </p>
          </div>

          <div className="dropzone">
            <FileText aria-hidden="true" size={48} />
            <strong>Select bank statement PDFs</strong>
            <input
              type="file"
              accept="application/pdf"
              multiple
              onChange={handleFileChange}
              disabled={isProcessing}
            />
            {files.length > 0 && (
              <span>
                {files.length} file{files.length === 1 ? "" : "s"} selected
              </span>
            )}
            <button
              type="button"
              onClick={handleRun}
              disabled={isProcessing || files.length === 0}
            >
              {isProcessing ? "Processing..." : "Run"}
            </button>
            {error && <p className="error-message">{error}</p>}
          </div>
        </section>
      </section>
    </main>
  );
}

export default App;
