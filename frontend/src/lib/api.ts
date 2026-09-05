const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type StageStatus = "pending" | "processing" | "done" | "error";

export interface JobStatusDTO {
  job_id: string;
  filenames: string[];
  created_at: number;
  extract: StageStatus;
  verify: StageStatus;
  enrich: StageStatus;
  ready: boolean;
  error: string | null;
}

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    return body?.error ?? body?.detail ?? fallback;
  } catch {
    return fallback;
  }
}

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/health`);

  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }

  return response.json();
}

/** Submits a batch of PDFs for processing. Returns immediately with a
 * job_id -- the pipeline runs in the background, so this does not block
 * further submissions. */
export async function submitProcessJob(files: File[]): Promise<{ job_id: string }> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }

  const response = await fetch(`${API_BASE_URL}/api/process`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Request failed with status ${response.status}`));
  }

  return response.json();
}

export async function fetchJobs(): Promise<JobStatusDTO[]> {
  const response = await fetch(`${API_BASE_URL}/api/jobs`);

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, `Failed to fetch jobs (${response.status})`));
  }

  return response.json();
}

export function jobDownloadUrl(jobId: string): string {
  return `${API_BASE_URL}/api/jobs/${jobId}/download`;
}
