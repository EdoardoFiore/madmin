# DNS Server Module

Modulo MADMIN per la gestione completa di un server DNS basato su **BIND9**, ispirato alle funzionalità del DNS Server di FortiGate.

## Funzionalità

### Gestione Zone
- **Zone Master** — gestione completa dei record DNS tramite GUI
- **Zone Forward** — inoltra tutte le query per un dominio a DNS remoti
- **Zone Stub** — delega la risoluzione a server DNS remoti

### Tipi di Record Supportati
| Tipo | Descrizione |
|------|-------------|
| A | Mappa hostname a IPv4 |
| AAAA | Mappa hostname a IPv6 |
| CNAME | Alias verso altro hostname |
| MX | Mail Exchange (con priorità) |
| TXT | Testo libero (SPF, DKIM, etc.) |
| SRV | Service record (con priorità, peso, porta) |
| NS | Name Server delegato |
| PTR | Reverse DNS |

### Modalità Operative (stile FortiGate)

| Modalità | Comportamento |
|----------|---------------|
| **Ricorsivo** | Controlla le zone locali, poi inoltra ai forwarder upstream |
| **Solo Forwarding** | Inoltra tutte le query ai forwarder di sistema |
| **Non Ricorsivo** | Risponde solo dalle zone locali, non inoltra |

### Forwarder Condizionali
Instrada le query DNS per domini specifici verso server dedicati. Utile per risolvere domini di rete interna (es. `corp.internal`) tramite un DNS aziendale, mantenendo la risoluzione pubblica per tutto il resto.

### Test DNS Integrato
Verifica la risoluzione DNS direttamente dalla GUI tramite `dig @localhost`.

## Struttura

```
modules/dns/
├── manifest.json              # Manifest del modulo
├── models.py                  # Modelli DB (SQLModel) + Pydantic schemas
├── service.py                 # Logica business, generazione config, firewall
├── router.py                  # API endpoints FastAPI
├── hooks/
│   ├── post_install.py        # Setup post-installazione
│   └── on_disable.py          # Cleanup alla disattivazione
├── migrations/
│   └── 001_initial.py         # Migrazione tabelle DB
├── templates/
│   ├── named.conf.options.j2  # Template opzioni globali BIND9
│   ├── named.conf.local.j2    # Template zone e forwarder
│   └── zone.j2                # Template file di zona
└── static/
    └── views/
        └── main.js            # Frontend (4 tab)
```

## Tabelle Database

| Tabella | Descrizione |
|---------|-------------|
| `dns_settings` | Configurazione globale (modalità, forwarder, interfacce) |
| `dns_zone` | Zone DNS con parametri SOA |
| `dns_record` | Record DNS di ogni zona |
| `dns_forwarder` | Forwarder condizionali per dominio |

## API Endpoints

| Metodo | Path | Descrizione |
|--------|------|-------------|
| GET | `/api/modules/dns/status` | Stato servizio + statistiche |
| POST | `/api/modules/dns/apply` | Genera config + restart bind9 |
| POST | `/api/modules/dns/start` | Avvia bind9 |
| POST | `/api/modules/dns/stop` | Ferma bind9 |
| GET/PUT | `/api/modules/dns/settings` | Impostazioni globali |
| GET/POST | `/api/modules/dns/zones` | Lista/crea zone |
| GET/PATCH/DELETE | `/api/modules/dns/zones/{id}` | Dettaglio/modifica/elimina zona |
| GET/POST | `/api/modules/dns/zones/{id}/records` | Record di una zona |
| PATCH/DELETE | `/api/modules/dns/records/{id}` | Modifica/elimina record |
| GET/POST/PATCH/DELETE | `/api/modules/dns/forwarders` | Forwarder condizionali |
| POST | `/api/modules/dns/test` | Test query DNS |

## Dipendenze di Sistema

- `bind9` — server DNS
- `bind9-utils` — strumenti di gestione (`named-checkconf`, `named-checkzone`)
- `dnsutils` — strumenti di query (`dig`)

## Integrazione Core

- **Firewall**: utilizza `core.firewall.iptables` per aprire le porte 53 UDP/TCP
- **Servizi**: utilizza `core.services.service.SystemdService` per il controllo del servizio
- **Permessi**: `dns.view` (visualizzazione), `dns.manage` (servizio/settings/forwarder), `dns.zones` (CRUD zone), `dns.records` (CRUD record)

## Workflow

1. Installa il modulo dalla pagina Moduli
2. Configura le impostazioni globali (modalità, forwarder)
3. Crea le zone DNS necessarie
4. Aggiungi i record nelle zone master
5. Configura eventuali forwarder condizionali
6. Clicca "Applica Config" per generare i file, validare e riavviare bind9
