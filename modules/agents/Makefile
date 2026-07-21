SHELL := /bin/bash
.DEFAULT_GOAL := help

# Usage:
#   make new-agent <name>          # e.g. `make new-agent oracle`
#   make new-agent NAME=<name>     # equivalent
#   make publish <name>            # publish <name> to Teams / M365 Copilot
#   make list-agents
#   make help

# --- positional-arg trick ----------------------------------------------------
# Lets `make new-agent foo` / `make publish foo` work without quoting NAME=foo.
ifeq (new-agent,$(firstword $(MAKECMDGOALS)))
  POS_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(POS_ARGS),)
    NAME ?= $(firstword $(POS_ARGS))
    $(eval $(POS_ARGS):;@:)
  endif
endif
ifeq (publish,$(firstword $(MAKECMDGOALS)))
  POS_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(POS_ARGS),)
    AGENT ?= $(firstword $(POS_ARGS))
    $(eval $(POS_ARGS):;@:)
  endif
endif
ifeq (unpublish,$(firstword $(MAKECMDGOALS)))
  POS_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(POS_ARGS),)
    AGENT ?= $(firstword $(POS_ARGS))
    $(eval $(POS_ARGS):;@:)
  endif
endif
ifeq (teams-config,$(firstword $(MAKECMDGOALS)))
  POS_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(POS_ARGS),)
    AGENT ?= $(firstword $(POS_ARGS))
    $(eval $(POS_ARGS):;@:)
  endif
endif
ifeq (grants,$(firstword $(MAKECMDGOALS)))
  POS_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(POS_ARGS),)
    AGENT ?= $(firstword $(POS_ARGS))
    $(eval $(POS_ARGS):;@:)
  endif
endif
ifeq (grant-hires,$(firstword $(MAKECMDGOALS)))
  POS_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(POS_ARGS),)
    AGENT ?= $(firstword $(POS_ARGS))
    $(eval $(POS_ARGS):;@:)
  endif
endif
ifeq (next-steps,$(firstword $(MAKECMDGOALS)))
  POS_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(POS_ARGS),)
    AGENT ?= $(firstword $(POS_ARGS))
    $(eval $(POS_ARGS):;@:)
  endif
endif
AGENTS_DIR := agents
TEMPLATE_DIR := $(AGENTS_DIR)/_template

.PHONY: help new-agent list-agents publish unpublish next-steps teams-config grants grant-hires waypoint-iq-auth analyst-waypoint-tool contracts-kb-seed contracts-kb-reindex

help:
	@echo "Targets:"
	@echo "  make new-agent <name>     Scaffold a new agent from agents/_template"
	@echo "                            and add a services entry to azure.yaml."
	@echo "  make publish <name>       Publish <name> to Microsoft 365 / Teams."
	@echo "                            Requires agents/<name>/publish.yaml."
	@echo "  make next-steps <name>    Re-print the manual next-steps banner"
	@echo "                            (admin approval, Teams Dev Portal, hiring)"
	@echo "                            for an already-published <name>."
	@echo "  make teams-config <name>  Configure the Teams Developer Portal"
	@echo "                            backend for <name> (AI teammate flow)."
	@echo "                            Requires az login with dev.teams scope."
	@echo "  make grants <name>        Grant OAuth2 admin consent on <name>'s"
	@echo "                            blueprint SP for APX + Prod MCP. Required"
	@echo "                            for the bot/agent to actually respond."
	@echo "                            Requires Application Administrator (or higher)."
	@echo "  make grant-hires <name>   Grant the Foundry User role on the account"
	@echo "                            and project to every per-instance MI of <name>."
	@echo "                            Run after the first AI Teammate is hired in M365."
	@echo "                            Also runs automatically as the last step of"
	@echo "                            'make publish' (no-op until first hire)."
	@echo "  make list-agents          List discoverable agents."
	@echo "  make contracts-kb-seed    Idempotently ensure the Foundry IQ knowledge"
	@echo "                            base contracts-kb / contracts-ks + MCP connection"
	@echo "                            over the already-uploaded corpus, then reindex."
	@echo "                            SKIP_UPLOAD=false uploads from a sibling Ledgerfield"
	@echo "                            checkout instead (LEDGERFIELD_ROOT=<path>)."
	@echo "  make contracts-kb-reindex Trigger an immediate run of contracts-ks-indexer."
	@echo "  make setup-oidc SUBSCRIPTION_ID=<sub>"
	@echo "                            Bootstrap GitHub Actions OIDC for this repo:"
	@echo "                            fresh Entra app + federated credentials +"
	@echo "                            subscription roles + repo variables. Adds the"
	@echo "                            reusable-workflow caller trust (keystone umbrella)."
	@echo "                            One-time per repo/tenant. Requires az login."
	@echo ""
	@echo "Examples:"
	@echo "  make new-agent oracle"
	@echo "  make new-agent NAME=oracle"
	@echo "  make publish rhodes"

list-agents:
	@python3 scripts/discover_agents.py

# --- GitHub Actions OIDC bootstrap (one-time per repo/tenant) ---
# Stands up a fresh Entra app dedicated to this repo so the deploy workflow can
# `az login` with OIDC (no secrets). Defaults wire the reusable-workflow caller
# trust (so the keystone umbrella can call forge's deploy.yml) and write the
# AZURE_* repo variables. Override OIDC_* / ROLES as needed.
OIDC_OWNER    ?= caldova
OIDC_REPO     ?= forge
OIDC_APP_NAME ?= forge-gha-oidc
OIDC_BRANCH   ?= main
OIDC_LOCATION ?= swedencentral
OIDC_ENV_NAME ?= forge

setup-oidc:
	@if [ -z "$(SUBSCRIPTION_ID)" ]; then \
		echo "ERROR: SUBSCRIPTION_ID required."; \
		echo "  make setup-oidc SUBSCRIPTION_ID=<sub> [OIDC_OWNER=caldova OIDC_REPO=forge OIDC_BRANCH=main]"; \
		exit 1; \
	fi
	@bash scripts/oidc.sh \
		--owner "$(OIDC_OWNER)" --repo "$(OIDC_REPO)" \
		--subscription-id "$(SUBSCRIPTION_ID)" \
		--app-name "$(OIDC_APP_NAME)" --branch "$(OIDC_BRANCH)" \
		--location "$(OIDC_LOCATION)" --env-name "$(OIDC_ENV_NAME)" \
		--pull-request --reusable-callers

new-agent:
	@if [ -z "$(NAME)" ]; then \
		echo "ERROR: agent name required."; \
		echo "  make new-agent <name>"; \
		echo "  make new-agent NAME=<name>"; \
		exit 1; \
	fi
	@case "$(NAME)" in \
		_*|.*) echo "ERROR: name cannot start with '_' or '.'"; exit 1;; \
		*[!a-zA-Z0-9-]*) echo "ERROR: only letters, digits, and dashes allowed."; exit 1;; \
	esac
	@if [ -e "$(AGENTS_DIR)/$(NAME)" ]; then \
		echo "ERROR: $(AGENTS_DIR)/$(NAME) already exists."; exit 1; \
	fi
	@if grep -qE "^[[:space:]]+$(NAME):[[:space:]]*$$" azure.yaml; then \
		echo "ERROR: azure.yaml already has a service named '$(NAME)'."; exit 1; \
	fi
	@echo ">> Copying template -> $(AGENTS_DIR)/$(NAME)"
	@cp -r $(TEMPLATE_DIR) $(AGENTS_DIR)/$(NAME)
	@find $(AGENTS_DIR)/$(NAME) -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

	@echo ">> Substituting placeholder names in agent.yaml / toolbox.py"
	@# Use a portable sed (works on both BSD/macOS and GNU/Linux)
	@sed -i.bak -e 's/name: my-new-agent/name: $(NAME)/' $(AGENTS_DIR)/$(NAME)/agent.yaml && rm $(AGENTS_DIR)/$(NAME)/agent.yaml.bak
	@sed -i.bak -e 's/my-new-agent/$(NAME)/g' $(AGENTS_DIR)/$(NAME)/toolbox.py && rm $(AGENTS_DIR)/$(NAME)/toolbox.py.bak

	@echo ">> Appending '$(NAME)' service to azure.yaml"
	@python3 scripts/add_agent_to_azure_yaml.py "$(NAME)"

	@echo ""
	@echo "Done. Next steps:"
	@echo "  1. Edit  $(AGENTS_DIR)/$(NAME)/main.py        (instructions)"
	@echo "  2. Edit  $(AGENTS_DIR)/$(NAME)/toolbox.py     (TOOLBOX list)"
	@echo "  3. Tweak $(AGENTS_DIR)/$(NAME)/agent.yaml     (cpu / memory if needed)"
	@echo "  4. git add $(AGENTS_DIR)/$(NAME) azure.yaml && git commit && git push"

publish:
	@if [ -z "$(AGENT)" ]; then \
		echo "ERROR: agent name required."; \
		echo "  make publish <name>"; \
		echo "  make publish AGENT=<name>"; \
		exit 1; \
	fi
	@if [ ! -f "$(AGENTS_DIR)/$(AGENT)/publish.yaml" ]; then \
		echo "ERROR: $(AGENTS_DIR)/$(AGENT)/publish.yaml not found."; \
		echo "Create one from $(TEMPLATE_DIR)/publish.yaml first."; \
		exit 1; \
	fi
	@echo ">> Resolving Foundry endpoint..."
	@# Prefer azd env values; fall back to parsing AZURE_AI_PROJECT_ENDPOINT
	@# (https://<account>.services.ai.azure.com/api/projects/<project>) and
	@# querying Azure for resource group + location. Lets `make publish` work
	@# from a workspace whose azd env was provisioned in a different name.
	@# NOTE: `azd env get-value` writes errors to stdout on missing keys, so
	@# we read the full env once and grep for known names.
	@AZD_ENV=$$(azd env get-values 2>/dev/null || true); \
	 get_azd() { printf '%s\n' "$$AZD_ENV" | sed -nE "s/^$$1=\"?([^\"]*)\"?$$/\1/p" | head -1; }; \
	 PROJECT_ENDPOINT=$$(get_azd AZURE_AI_PROJECT_ENDPOINT); \
	 if [ -z "$$PROJECT_ENDPOINT" ]; then \
	   echo "ERROR: AZURE_AI_PROJECT_ENDPOINT not in azd env. Run 'azd env get-values' to check."; exit 1; \
	 fi; \
	 ACCOUNT_NAME=$$(get_azd AZURE_AI_ACCOUNT_NAME); \
	 if [ -z "$$ACCOUNT_NAME" ]; then \
	   ACCOUNT_NAME=$$(printf '%s' "$$PROJECT_ENDPOINT" | sed -E 's#^https://([^.]+)\..*#\1#'); \
	 fi; \
	 PROJECT_NAME=$$(get_azd AZURE_AI_PROJECT_NAME); \
	 if [ -z "$$PROJECT_NAME" ]; then \
	   PROJECT_NAME=$$(printf '%s' "$$PROJECT_ENDPOINT" | sed -E 's#.*/projects/([^/?]+).*#\1#'); \
	 fi; \
	 SUBSCRIPTION_ID=$$(az account show --query id -o tsv); \
	 RESOURCE_GROUP=$$(get_azd AZURE_RESOURCE_GROUP); \
	 if [ -z "$$RESOURCE_GROUP" ]; then \
	   RESOURCE_GROUP=$$(az cognitiveservices account list --query "[?name=='$$ACCOUNT_NAME'].resourceGroup | [0]" -o tsv); \
	 fi; \
	 LOCATION=$$(get_azd AZURE_LOCATION); \
	 if [ -z "$$LOCATION" ]; then \
	   LOCATION=$$(az cognitiveservices account show -n "$$ACCOUNT_NAME" -g "$$RESOURCE_GROUP" --query location -o tsv); \
	 fi; \
	 echo "   account=$$ACCOUNT_NAME project=$$PROJECT_NAME rg=$$RESOURCE_GROUP loc=$$LOCATION"; \
	 echo ""; \
	 echo ">> Patching agent endpoint to BotServiceRbac-only auth (no Foundry login prompt)..."; \
	 AGENT_NAME=$(AGENT) PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 python3 scripts/patch_agent_endpoint.py; \
	 echo ""; \
	 echo ">> Ensuring Bot Service + Teams channel for $(AGENT)..."; \
	 AGENT_NAME=$(AGENT) \
	 PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 ACCOUNT_NAME=$$ACCOUNT_NAME \
	 PROJECT_NAME=$$PROJECT_NAME \
	 RESOURCE_GROUP=$$RESOURCE_GROUP \
	 SUBSCRIPTION_ID=$$SUBSCRIPTION_ID \
	 PUBLISH_CONFIG=$(AGENTS_DIR)/$(AGENT)/publish.yaml \
	 python3 scripts/ensure_bot_service.py; \
	 echo ""; \
	 echo ">> Ensuring Foundry Application resource (Teams 'Built for your org' catalog)..."; \
	 AGENT_NAME=$(AGENT) \
	 ACCOUNT_NAME=$$ACCOUNT_NAME \
	 PROJECT_NAME=$$PROJECT_NAME \
	 RESOURCE_GROUP=$$RESOURCE_GROUP \
	 SUBSCRIPTION_ID=$$SUBSCRIPTION_ID \
	 python3 scripts/ensure_foundry_application.py; \
	 echo ""; \
	 AGENT_NAME=$(AGENT) \
	 PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 ACCOUNT_NAME=$$ACCOUNT_NAME \
	 PROJECT_NAME=$$PROJECT_NAME \
	 RESOURCE_GROUP=$$RESOURCE_GROUP \
	 LOCATION=$$LOCATION \
	 SUBSCRIPTION_ID=$$SUBSCRIPTION_ID \
	 PUBLISH_CONFIG=$(AGENTS_DIR)/$(AGENT)/publish.yaml \
	 python3 scripts/publish_agent.py
	@echo ""
	@echo ">> Granting OAuth2 admin consent on the blueprint SP (APX + Prod MCP)..."
	@PROJECT_ENDPOINT=$$(azd env get-values 2>/dev/null | sed -nE 's/^AZURE_AI_PROJECT_ENDPOINT="?([^"]*)"?$$/\1/p' | head -1); \
	 AGENT_NAME=$(AGENT) PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 python3 scripts/grant_blueprint_oauth2.py
	@echo ""
	@echo ">> Granting Foundry User role to existing per-instance MIs (no-op if none yet)..."
	@AZD_ENV=$$(azd env get-values 2>/dev/null || true); \
	 get_azd() { printf '%s\n' "$$AZD_ENV" | sed -nE "s/^$$1=\"?([^\"]*)\"?$$/\1/p" | head -1; }; \
	 PROJECT_ENDPOINT=$$(get_azd AZURE_AI_PROJECT_ENDPOINT); \
	 ACCOUNT_NAME=$$(get_azd AZURE_AI_ACCOUNT_NAME); \
	 if [ -z "$$ACCOUNT_NAME" ]; then ACCOUNT_NAME=$$(printf '%s' "$$PROJECT_ENDPOINT" | sed -E 's#^https://([^.]+)\..*#\1#'); fi; \
	 PROJECT_NAME=$$(get_azd AZURE_AI_PROJECT_NAME); \
	 if [ -z "$$PROJECT_NAME" ]; then PROJECT_NAME=$$(printf '%s' "$$PROJECT_ENDPOINT" | sed -E 's#.*/projects/([^/?]+).*#\1#'); fi; \
	 RESOURCE_GROUP=$$(get_azd AZURE_RESOURCE_GROUP); \
	 if [ -z "$$RESOURCE_GROUP" ]; then RESOURCE_GROUP=$$(az cognitiveservices account list --query "[?name=='$$ACCOUNT_NAME'].resourceGroup | [0]" -o tsv); fi; \
	 SUBSCRIPTION_ID=$$(az account show --query id -o tsv); \
	 AGENT_UPPER=$$(printf '%s' "$(AGENT)" | tr '[:lower:]-' '[:upper:]_'); \
	 BLUEPRINT_CLIENT_ID=$$(get_azd $${AGENT_UPPER}_BLUEPRINT_CLIENT_ID); \
	 AGENT_NAME=$(AGENT) \
	 ACCOUNT_NAME=$$ACCOUNT_NAME \
	 PROJECT_NAME=$$PROJECT_NAME \
	 RESOURCE_GROUP=$$RESOURCE_GROUP \
	 SUBSCRIPTION_ID=$$SUBSCRIPTION_ID \
	 BLUEPRINT_CLIENT_ID=$$BLUEPRINT_CLIENT_ID \
	 python3 scripts/grant_instance_mi_roles.py
	@echo ""
	@PROJECT_ENDPOINT=$$(azd env get-values 2>/dev/null | sed -nE 's/^AZURE_AI_PROJECT_ENDPOINT="?([^"]*)"?$$/\1/p' | head -1); \
	 AGENT_NAME=$(AGENT) PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 PUBLISH_CONFIG=$(AGENTS_DIR)/$(AGENT)/publish.yaml \
	 python3 scripts/print_publish_next_steps.py

grant-hires:
	@if [ -z "$(AGENT)" ]; then \
		echo "ERROR: agent name required."; \
		echo "  make grant-hires <name>"; \
		exit 1; \
	fi
	@AZD_ENV=$$(azd env get-values 2>/dev/null || true); \
	 get_azd() { printf '%s\n' "$$AZD_ENV" | sed -nE "s/^$$1=\"?([^\"]*)\"?$$/\1/p" | head -1; }; \
	 PROJECT_ENDPOINT=$$(get_azd AZURE_AI_PROJECT_ENDPOINT); \
	 if [ -z "$$PROJECT_ENDPOINT" ]; then \
	   echo "ERROR: AZURE_AI_PROJECT_ENDPOINT not in azd env."; exit 1; \
	 fi; \
	 ACCOUNT_NAME=$$(get_azd AZURE_AI_ACCOUNT_NAME); \
	 if [ -z "$$ACCOUNT_NAME" ]; then ACCOUNT_NAME=$$(printf '%s' "$$PROJECT_ENDPOINT" | sed -E 's#^https://([^.]+)\..*#\1#'); fi; \
	 PROJECT_NAME=$$(get_azd AZURE_AI_PROJECT_NAME); \
	 if [ -z "$$PROJECT_NAME" ]; then PROJECT_NAME=$$(printf '%s' "$$PROJECT_ENDPOINT" | sed -E 's#.*/projects/([^/?]+).*#\1#'); fi; \
	 RESOURCE_GROUP=$$(get_azd AZURE_RESOURCE_GROUP); \
	 if [ -z "$$RESOURCE_GROUP" ]; then RESOURCE_GROUP=$$(az cognitiveservices account list --query "[?name=='$$ACCOUNT_NAME'].resourceGroup | [0]" -o tsv); fi; \
	 SUBSCRIPTION_ID=$$(az account show --query id -o tsv); \
	 AGENT_UPPER=$$(printf '%s' "$(AGENT)" | tr '[:lower:]-' '[:upper:]_'); \
	 BLUEPRINT_CLIENT_ID=$$(get_azd $${AGENT_UPPER}_BLUEPRINT_CLIENT_ID); \
	 AGENT_NAME=$(AGENT) \
	 ACCOUNT_NAME=$$ACCOUNT_NAME \
	 PROJECT_NAME=$$PROJECT_NAME \
	 RESOURCE_GROUP=$$RESOURCE_GROUP \
	 SUBSCRIPTION_ID=$$SUBSCRIPTION_ID \
	 BLUEPRINT_CLIENT_ID=$$BLUEPRINT_CLIENT_ID \
	 python3 scripts/grant_instance_mi_roles.py

unpublish:
	@if [ -z "$(AGENT)" ]; then \
		echo "ERROR: agent name required."; \
		echo "  make unpublish <name>"; \
		echo "  make unpublish AGENT=<name> [AGENT_IDENTITY=<guid>] [DRY_RUN=1]"; \
		exit 1; \
	fi
	@AZD_ENV=$$(azd env get-values 2>/dev/null || true); \
	 get_azd() { printf '%s\n' "$$AZD_ENV" | sed -nE "s/^$$1=\"?([^\"]*)\"?$$/\1/p" | head -1; }; \
	 PROJECT_ENDPOINT=$$(get_azd AZURE_AI_PROJECT_ENDPOINT); \
	 ACCOUNT_NAME=$$(get_azd AZURE_AI_ACCOUNT_NAME); \
	 if [ -z "$$ACCOUNT_NAME" ]; then ACCOUNT_NAME=$$(printf '%s' "$$PROJECT_ENDPOINT" | sed -E 's#^https://([^.]+)\..*#\1#'); fi; \
	 PROJECT_NAME=$$(get_azd AZURE_AI_PROJECT_NAME); \
	 if [ -z "$$PROJECT_NAME" ]; then PROJECT_NAME=$$(printf '%s' "$$PROJECT_ENDPOINT" | sed -E 's#.*/projects/([^/?]+).*#\1#'); fi; \
	 SUBSCRIPTION_ID=$$(az account show --query id -o tsv); \
	 TENANT_ID=$$(az account show --query tenantId -o tsv); \
	 RESOURCE_GROUP=$$(get_azd AZURE_RESOURCE_GROUP); \
	 if [ -z "$$RESOURCE_GROUP" ]; then \
	   RESOURCE_GROUP=$$(az cognitiveservices account list --query "[?name=='$$ACCOUNT_NAME'].resourceGroup | [0]" -o tsv); \
	 fi; \
	 EXTRA=""; \
	 if [ -n "$(AGENT_IDENTITY)" ]; then EXTRA="$$EXTRA --agent-identity $(AGENT_IDENTITY)"; fi; \
	 if [ -n "$(DRY_RUN)" ]; then EXTRA="$$EXTRA --dry-run"; fi; \
	 AGENT_NAME=$(AGENT) \
	 PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 ACCOUNT_NAME=$$ACCOUNT_NAME \
	 PROJECT_NAME=$$PROJECT_NAME \
	 RESOURCE_GROUP=$$RESOURCE_GROUP \
	 SUBSCRIPTION_ID=$$SUBSCRIPTION_ID \
	 TENANT_ID=$$TENANT_ID \
	 python3 scripts/unpublish_agent.py $$EXTRA

next-steps:
	@if [ -z "$(AGENT)" ]; then \
		echo "ERROR: agent name required."; \
		echo "  make next-steps <name>"; \
		exit 1; \
	fi
	@PROJECT_ENDPOINT=$$(azd env get-values 2>/dev/null | sed -nE 's/^AZURE_AI_PROJECT_ENDPOINT="?([^"]*)"?$$/\1/p' | head -1); \
	 if [ -z "$$PROJECT_ENDPOINT" ]; then \
	   echo "ERROR: AZURE_AI_PROJECT_ENDPOINT not in azd env."; exit 1; \
	 fi; \
	 AGENT_NAME=$(AGENT) PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 PUBLISH_CONFIG=$(AGENTS_DIR)/$(AGENT)/publish.yaml \
	 python3 scripts/print_publish_next_steps.py

grants:
	@if [ -z "$(AGENT)" ]; then \
		echo "ERROR: agent name required."; \
		echo "  make grants <name>"; \
		exit 1; \
	fi
	@PROJECT_ENDPOINT=$$(azd env get-values 2>/dev/null | sed -nE 's/^AZURE_AI_PROJECT_ENDPOINT="?([^"]*)"?$$/\1/p' | head -1); \
	 if [ -z "$$PROJECT_ENDPOINT" ]; then \
	   echo "ERROR: AZURE_AI_PROJECT_ENDPOINT not in azd env."; exit 1; \
	 fi; \
	 AGENT_NAME=$(AGENT) PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 python3 scripts/grant_blueprint_oauth2.py

teams-config:
	@if [ -z "$(AGENT)" ]; then \
		echo "ERROR: agent name required."; \
		echo "  make teams-config <name>"; \
		echo "  make teams-config AGENT=<name>"; \
		exit 1; \
	fi
	@echo ">> Configuring Teams Developer Portal backend for $(AGENT)..."
	@echo "   (requires user-context token; ensure you've run:"
	@echo "      az login --scope https://dev.teams.microsoft.com/.default )"
	@PROJECT_ENDPOINT=$$(azd env get-values 2>/dev/null | sed -nE 's/^AZURE_AI_PROJECT_ENDPOINT="?([^"]*)"?$$/\1/p' | head -1); \
	 if [ -z "$$PROJECT_ENDPOINT" ]; then \
	   echo "ERROR: AZURE_AI_PROJECT_ENDPOINT not in azd env."; exit 1; \
	 fi; \
	 echo ">> Ensuring current user is owner of the blueprint app..."; \
	 AI_TOKEN=$$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv); \
	 BLUEPRINT=$$(curl -sf -H "Authorization: Bearer $$AI_TOKEN" -H "Foundry-Features: HostedAgents=V1Preview,AgentEndpoints=V1Preview" "$$PROJECT_ENDPOINT/agents/$(AGENT)?api-version=2025-11-15-preview" | python3 -c "import sys,json;a=json.load(sys.stdin);v=a.get('versions',{}).get('latest',{});print(v.get('blueprint',{}).get('client_id') or a.get('blueprint',{}).get('client_id') or '')"); \
	 USER_ID=$$(az ad signed-in-user show --query id -o tsv); \
	 if [ -n "$$BLUEPRINT" ] && [ -n "$$USER_ID" ]; then \
	   OUT=$$(az ad app owner add --id "$$BLUEPRINT" --owner-object-id "$$USER_ID" 2>&1) || true; \
	   if [ -n "$$OUT" ] && ! printf '%s' "$$OUT" | grep -qiE 'already|reference already exists'; then \
	     echo "   (owner add note: $$OUT)"; \
	   else \
	     echo "   ok"; \
	   fi; \
	 fi; \
	 AGENT_NAME=$(AGENT) \
	 PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 python3 scripts/configure_teams_blueprint.py

waypoint-iq-auth:
	@echo ">> Ensuring waypoint-iq toolbox uses managed-identity auth (project MI, doc-canonical)..."
	@PROJECT_ENDPOINT=$$(azd env get-values 2>/dev/null | sed -nE 's/^AZURE_AI_PROJECT_ENDPOINT="?([^"]*)"?$$/\1/p' | head -1); \
	 if [ -z "$$PROJECT_ENDPOINT" ]; then \
	   echo "ERROR: AZURE_AI_PROJECT_ENDPOINT not in azd env. Run 'azd env get-values' to check."; exit 1; \
	 fi; \
	 FOUNDRY_PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 python3 scripts/ensure_waypoint_iq_managed_identity.py $(if $(AUDIENCE),--audience $(AUDIENCE),)

analyst-waypoint-tool:
	@echo ">> Merging read-only WaypointIQ into invoice-analyst-tools toolbox..."
	@PROJECT_ENDPOINT=$$(azd env get-values 2>/dev/null | sed -nE 's/^AZURE_AI_PROJECT_ENDPOINT="?([^"]*)"?$$/\1/p' | head -1); \
	 if [ -z "$$PROJECT_ENDPOINT" ]; then \
	   echo "ERROR: AZURE_AI_PROJECT_ENDPOINT not in azd env. Run 'azd env get-values' to check."; exit 1; \
	 fi; \
	 FOUNDRY_PROJECT_ENDPOINT=$$PROJECT_ENDPOINT \
	 python3 scripts/ensure_analyst_waypoint_tool.py

# --- contracts-kb data-plane (idempotent, no portal steps) -------------------
# Ensures the Foundry IQ knowledge base contracts-kb / knowledge source
# contracts-ks / kb-mcp-connection over the corpus already uploaded to the
# storage container (Ledgerfield owns upload via `ledgerfield upload-contracts-kb`
# / its contracts-kb-upload workflow). Coordinates are resolved from the azd env
# outputs, with `az resource list` fallback inside the script.
#
#   make contracts-kb-seed                      # KB/KS over existing corpus + reindex
#   make contracts-kb-seed SKIP_UPLOAD=false \
#        LEDGERFIELD_ROOT=../ledgerfield        # self-contained forge upload + KB + reindex
#   make contracts-kb-seed SKIP_UPLOAD=false \
#        LEDGERFIELD_ROOT=../ledgerfield PRUNE_STALE=true  # + delete stale (renamed) blobs
#   make contracts-kb-reindex                   # just re-run contracts-ks-indexer
SKIP_UPLOAD ?= true
RUN_INDEXER ?= true
PRUNE_STALE ?= false

define _azd_get
$$(azd env get-values 2>/dev/null | sed -nE 's/^$(1)="?([^"]*)"?$$/\1/p' | grep -v 'not found' | head -1)
endef

contracts-kb-seed:
	@echo ">> Ensuring contracts-kb / contracts-ks (skip_upload=$(SKIP_UPLOAD) run_indexer=$(RUN_INDEXER))..."
	@set -e; \
	 export AZURE_RESOURCE_GROUP="$${AZURE_RESOURCE_GROUP:-$(call _azd_get,AZURE_RESOURCE_GROUP)}"; \
	 [ -n "$$AZURE_RESOURCE_GROUP" ] || export AZURE_RESOURCE_GROUP="rg-$${AZD_ENV_NAME:-forge}"; \
	 export AZURE_STORAGE_ACCOUNT_NAME="$${AZURE_STORAGE_ACCOUNT_NAME:-$(call _azd_get,AZURE_STORAGE_ACCOUNT_NAME)}"; \
	 export AZURE_STORAGE_CONTAINER_NAME="$${AZURE_STORAGE_CONTAINER_NAME:-$(call _azd_get,AZURE_AI_SEARCH_CONTAINER_NAME)}"; \
	 [ -n "$$AZURE_STORAGE_CONTAINER_NAME" ] || export AZURE_STORAGE_CONTAINER_NAME="knowledge"; \
	 export AZURE_AI_SEARCH_SERVICE_NAME="$${AZURE_AI_SEARCH_SERVICE_NAME:-$(call _azd_get,AZURE_AI_SEARCH_SERVICE_NAME)}"; \
	 export AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME="$${AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME:-$(call _azd_get,AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME)}"; \
	 export AZURE_AI_SEARCH_KNOWLEDGE_SOURCE_NAME="$${AZURE_AI_SEARCH_KNOWLEDGE_SOURCE_NAME:-$(call _azd_get,AZURE_AI_SEARCH_KNOWLEDGE_SOURCE_NAME)}"; \
	 export AZURE_AI_SEARCH_KB_MCP_CONNECTION_NAME="$${AZURE_AI_SEARCH_KB_MCP_CONNECTION_NAME:-$(call _azd_get,AZURE_AI_SEARCH_KB_MCP_CONNECTION_NAME)}"; \
	 export AZURE_AI_MODEL_DEPLOYMENT_NAME="$${AZURE_AI_MODEL_DEPLOYMENT_NAME:-$(call _azd_get,AZURE_AI_MODEL_DEPLOYMENT_NAME)}"; \
	 export AZURE_AI_EMBEDDING_DEPLOYMENT_NAME="$${AZURE_AI_EMBEDDING_DEPLOYMENT_NAME:-$(call _azd_get,AZURE_AI_EMBEDDING_DEPLOYMENT_NAME)}"; \
	 ARGS=""; \
	 if [ "$(SKIP_UPLOAD)" = "true" ]; then ARGS="$$ARGS --skip-upload"; \
	 elif [ -n "$(LEDGERFIELD_ROOT)" ]; then ARGS="$$ARGS --ledgerfield-root $(LEDGERFIELD_ROOT)"; fi; \
	 if [ "$(SKIP_UPLOAD)" != "true" ] && [ "$(PRUNE_STALE)" = "true" ]; then ARGS="$$ARGS --prune-stale"; fi; \
	 if [ "$(RUN_INDEXER)" = "true" ]; then ARGS="$$ARGS --run-indexer"; fi; \
	 python3 scripts/initialize_contracts_kb.py $$ARGS

contracts-kb-reindex:
	@echo ">> Triggering contracts-ks-indexer run..."
	@set -e; \
	 SEARCH="$${AZURE_AI_SEARCH_SERVICE_NAME:-$(call _azd_get,AZURE_AI_SEARCH_SERVICE_NAME)}"; \
	 KS="$${AZURE_AI_SEARCH_KNOWLEDGE_SOURCE_NAME:-$(call _azd_get,AZURE_AI_SEARCH_KNOWLEDGE_SOURCE_NAME)}"; \
	 [ -n "$$KS" ] || KS="contracts-ks"; \
	 if [ -z "$$SEARCH" ]; then \
	   RG="$${AZURE_RESOURCE_GROUP:-rg-$${AZD_ENV_NAME:-forge}}"; \
	   SEARCH=$$(az resource list -g "$$RG" --query "[?type=='Microsoft.Search/searchServices'].name | [0]" -o tsv); \
	 fi; \
	 [ -n "$$SEARCH" ] || { echo "ERROR: could not resolve Azure AI Search service name."; exit 1; }; \
	 TOKEN=$$(az account get-access-token --resource https://search.azure.com --query accessToken -o tsv); \
	 echo "   search=$$SEARCH indexer=$$KS-indexer"; \
	 curl -sS -X POST -H "Authorization: Bearer $$TOKEN" -H "Content-Length: 0" \
	   "https://$$SEARCH.search.windows.net/indexers('$$KS-indexer')/run?api-version=2024-07-01" \
	   -o /dev/null -w "   indexer run HTTP %{http_code}\n"
