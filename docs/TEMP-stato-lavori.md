# Stato dei lavori (documento temporaneo)

Il riepilogo completo di Fase 0 e Fase 1 (cosa è stato fatto, come funziona,
procedure, test, limiti) è nella repo del manager:
`madmin-manager/docs/TEMP-stato-lavori.md` (branch `feat/manager-phase0`).

In questa repo (branch `feat/manager-agent`):

- agente: `backend/core/manager/` (protocollo in `protocol.py`, identico al manager)
- migrazioni del database: `backend/core/migrations/`, `backend/modules/<id>/upgrades/`
- release: `scripts/build-release.sh`, `scripts/sign-release.sh`, `scripts/release-key.sh`,
  chiavi pubbliche in `scripts/release-keys/`, procedura in `docs/RELEASING.md`
- updater e rescue: `scripts/madmin-update`, `scripts/madmin-rescue`
- installazione nel layout a release: `scripts/setup-madmin.sh`, `scripts/uninstall-madmin.sh`
- tag `agent-v1-baseline`: agente di riferimento del protocollo v1
