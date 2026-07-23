# Agent template

> **You probably want `make new-agent <name>` from the repo root** — it copies this folder, substitutes the name, and updates `azure.yaml` for you in one step.

## Manual setup

If you'd rather not use Make:

```bash
cp -r agents/_template agents/<your-agent-name>
```

Then:

1. **Edit `agent.yaml`** — change `name:` (this is the agent's identity in Foundry) and adjust `cpu` / `memory` if needed.
2. **Edit `main.py`** — replace the `instructions=...` string with your agent's persona / behavioral rules.
3. **Edit `toolbox.py`** — set `DESCRIPTION` and customize the `TOOLBOX` list with the tools the model should see.
4. **Add to `azure.yaml`** at the repo root, under `services:`:

   ```yaml
   <your-agent-name>:
     project: ./agents/<your-agent-name>
     host: azure.ai.agent
     language: docker
     docker:
       remoteBuild: true
     config:
       container:
         resources:
           cpu: "0.5"
           memory: 1Gi
       startupCommand: python main.py
   ```

5. **Commit and push** — CI auto-discovers the new folder, creates the toolbox, builds the container, and deploys.

## Publishing to Microsoft 365 / Teams (AI Teammate)

The template is already wired for the AI Teammate ("hired digital worker")
path — `agent.yaml` declares `activity_protocol/v1` and the full M365 Agents
SDK env block, and `main.py` mounts `/api/messages` via `activity_protocol.py`.
The mount is a no-op until you actually publish, so the Responses path is
unaffected on a stock deploy.

To get your agent into the M365 Copilot store and make hires reply in Teams:

1. **Publish.** From the repo root:

   ```bash
   make publish <your-agent-name>
   ```

   This chains: bot service + Teams channel → Foundry application →
   M365 publish request → OAuth2 grants on the blueprint SP.

2. **Reset the blueprint client secret.** *Mandatory.* Foundry's API redacts
   the secret to `""` on read, so a missing real value silently breaks every
   hire with AAD `-60018`. Run the `az ad app credential reset` + `azd env set
   <AGENT>_BLUEPRINT_CLIENT_ID/_SECRET` recipe printed by
   `scripts/print_publish_next_steps.py` (also documented in
   [docs/AI_TEAMMATE.md](../../docs/AI_TEAMMATE.md)), then redeploy.

3. **Add the per-instance MI federated credential** on the blueprint app
   manually (one-time, until the Foundry portal exposes a button) — see the
   same doc. Without it, hired chats fail with `AADSTS70021: No matching
   federated identity record found`.

4. **Admin-approve** the publish request at
   <https://admin.cloud.microsoft/#/agents/all/requested>.

For the full recipe, common failure modes, and the `version_selector → @latest`
trap, read [docs/AI_TEAMMATE.md](../../docs/AI_TEAMMATE.md) end-to-end before
your first publish.
