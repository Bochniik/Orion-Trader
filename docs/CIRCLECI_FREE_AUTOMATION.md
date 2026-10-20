# OrionTrader — free unattended cloud CI with CircleCI

GitHub Actions on this account currently rejects jobs before execution due to a billing/account restriction. This is an **alternative CI provider**, not a workaround that alters or weakens GitHub's security policy. The existing GitHub Actions workflows and their protections stay unchanged.

## One-time authorization by the repository owner

1. Open [CircleCI](https://circleci.com/signup/) and choose its **Free** plan. CircleCI currently advertises a free tier without a required payment card and an allowance of build credits. Never enable paid add-ons or overages.
2. Connect the **Bochniik/Orion-Trader** GitHub repository using the CircleCI GitHub integration. Grant access to this repository only; this is a third-party service that will read the selected repository's source code.
3. Configure a pipeline whose configuration source is `.circleci/config.yml` in this repository. Enable automatic **push and pull-request** triggers. The file must be accessible on the configuration branch selected during onboarding (usually `main`); if the config-only PR is not yet merged, first review/merge it or choose a supported config branch.
4. Verify that CircleCI runs **backend-regressions** and **frontend-regressions** on the exact target PR commit. A passing local test does not substitute for this evidence.

After this one-time setup, CircleCI runs in its own cloud: the user's Windows PC can be switched off. The configuration executes only deterministic tests and a frontend build. It does **not** fetch private API keys, place orders, modify the frozen OurAI V3 journal, deploy applications, or automatically merge PRs.

## Scope

Backend: OurAI bridge contract test when present (OrionTrader PR #397), Intelligence API, portfolio intelligence, market sessions, news service, and manifest-based analytics regressions. Python 3.12.

Frontend: all Vitest tests and the Vite production build. Node.js 24.

## Important limitations

- Free-tier compute credits are **finite**; jobs stop when the provider's quota is exhausted.
- Connecting CircleCI is an explicit action by the repo owner and has **not** been done merely by adding this configuration.
- GitHub Actions account restrictions may persist. CircleCI's passing status does not magically convert existing GitHub Actions failures to green or bypass required branch-protection checks.
- The user should approve any branch protection or auto-merge policy change separately. No automated merge is enabled here.
- No self-hosted runner or Windows PC needs to be kept on for this cloud-based test pipeline.
