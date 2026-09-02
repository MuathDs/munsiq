import { getAllJobs } from "@/lib/jobStore";

export async function GET() {
  return Response.json({ jobs: getAllJobs() });
}
