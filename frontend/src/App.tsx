import { FileText, Server } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import "./App.css";
import { type JobStatusDTO, type StageStatus, fetchJobs, getHealth, jobDownloadUrl, submitProcessJob } from "./lib/api";

type ApiStatus = "checking" | "online" | "offline";

const POLL_INTERVAL_MS = 1500;

const STAGE_LABEL: Record<StageStatus, string> = {
  pending: "Not started",
  processing: "Processing",
  done: "Ready",
  error: "Failed",
};

function StatusDot({ status }: { status: StageStatus }) {
  return (
    <span className="status-cell" title={STAGE_LABEL[status]}>
      <span className={`status-dot status-dot-${status}`} aria-hidden="true" />
      <span className="status-dot-label">{STAGE_LABEL[status]}</span>
    </span>
  );
}

function App() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [files, setFiles] = useState<File[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobStatusDTO[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getHealth()
      .then(() => setApiStatus("online"))
      .catch(() => setApiStatus("offline"));
  }, []);

  const refreshJobs = async () => {
    try {
      const latest = await fetchJobs();
      setJobs(latest);
    } catch {
      // transient poll failure -- keep showing the last known state
    }
  };

  useEffect(() => {
    refreshJobs();
    const interval = window.setInterval(refreshJobs, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setFiles(Array.from(event.target.files ?? []));
    setSubmitError(null);
  };

  const handleRun = async () => {
    if (files.length === 0) return;

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      await submitProcessJob(files);
      setFiles([]);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await refreshJobs();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="app-shell">
      <section className="workspace">
        <header className="topbar">
          <div className="brand">
            <FileText aria-hidden="true" size={24} />
            <span>SourceLine</span>
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
              Every transaction narrative is matched against your reference data by AI, then
              paired with a confidence score and a screenshot of its source page so an
              analyst can verify it before trusting it.
            </p>
          </div>

          <div className="dropzone">
            <FileText aria-hidden="true" size={48} />
            <strong>Select bank statement PDFs</strong>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf"
              multiple
              onChange={handleFileChange}
              disabled={isSubmitting}
            />
            {files.length > 0 && (
              <span>
                {files.length} file{files.length === 1 ? "" : "s"} selected
              </span>
            )}
            <button type="button" onClick={handleRun} disabled={isSubmitting || files.length === 0}>
              {isSubmitting ? "Queueing..." : "Run"}
            </button>
            {submitError && <p className="error-message">{submitError}</p>}
          </div>
        </section>

        <section className="jobs-section">
          <h2>Processing history</h2>
          {jobs.length === 0 ? (
            <p className="jobs-empty">No runs yet -- upload PDFs above and click Run.</p>
          ) : (
            <div className="jobs-table-wrap">
              <table className="jobs-table">
                <thead>
                  <tr>
                    <th>Files</th>
                    <th>Extract</th>
                    <th>Verify</th>
                    <th>Enrich</th>
                    <th>Download</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.job_id}>
                      <td className="jobs-filenames" title={job.filenames.join(", ")}>
                        {job.filenames.join(", ")}
                      </td>
                      <td>
                        <StatusDot status={job.extract} />
                      </td>
                      <td>
                        <StatusDot status={job.verify} />
                      </td>
                      <td>
                        <StatusDot status={job.enrich} />
                      </td>
                      <td>
                        {job.ready ? (
                          <a className="download-btn" href={jobDownloadUrl(job.job_id)}>
                            Download
                          </a>
                        ) : (
                          <button type="button" className="download-btn" disabled>
                            Download
                          </button>
                        )}
                        {job.error && (
                          <p className="jobs-error" title={job.error}>
                            {job.error}
                          </p>
                        )}
                        {job.failed_files.length > 0 && (
                          <p
                            className="jobs-error"
                            title={`Extraction failed for: ${job.failed_files.join(", ")}. A "review - extraction failed" row was added to the workbook for each.`}
                          >
                            Extraction failed for {job.failed_files.length} file
                            {job.failed_files.length > 1 ? "s" : ""}: {job.failed_files.join(", ")}
                          </p>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}

export default App;
