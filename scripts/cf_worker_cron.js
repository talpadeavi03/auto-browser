/**
 * Cloudflare Worker: 24/7 Precision GitHub Actions Scheduler
 * 
 * Free Tier: 100,000 requests/day (100% free forever)
 * Reliability: 99.99% uptime, executes on the exact second
 * 
 * Setup Instructions:
 * 1. Log into https://dash.cloudflare.com -> Workers & Pages -> Create Worker
 * 2. Paste this code into the worker.
 * 3. In Settings -> Variables, add Environment Variable or Secret:
 *    - GITHUB_PAT: Your GitHub Personal Access Token (Fine-grained with Actions Read/Write)
 * 4. In Settings -> Triggers, add a Cron Trigger:
 *    - "0 *\/3 * * *" (runs every 3 hours)
 */

export default {
  async scheduled(event, env, ctx) {
    const owner = "talpadeavi03";
    const repo = "auto-browser";
    const workflowFile = "job-automation.yml";
    const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflowFile}/dispatches`;

    const token = env.GITHUB_PAT;
    if (!token) {
      console.error("Missing GITHUB_PAT environment secret!");
      return;
    }

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "Cloudflare-Cron-Worker",
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        ref: "master",
        inputs: { action: "run-all" }
      })
    });

    if (response.status === 204) {
      console.log(`✓ Successfully triggered GitHub Actions workflow (${workflowFile})!`);
    } else {
      const errText = await response.text();
      console.error(`Failed to trigger workflow. Status: ${response.status}, Error: ${errText}`);
    }
  },

  async fetch(request, env, ctx) {
    return new Response("Auto-Browser Cloudflare Cron Worker is active! Triggered via cron schedule.", {
      headers: { "content-type": "text/plain" }
    });
  }
};
