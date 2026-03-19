# MADMIN — Manuale Utente

> Guida all'utilizzo del portale di gestione. Versione destinata agli utenti finali del pannello web.

---

## Indice

1. [Accesso al portale](#1-accesso-al-portale)
2. [Dashboard](#2-dashboard)
3. [Gestione Utenti](#3-gestione-utenti)
4. [Firewall](#4-firewall)
5. [Interfacce di Rete](#5-interfacce-di-rete)
6. [Moduli](#6-moduli)
   - [WireGuard VPN](#61-wireguard-vpn)
   - [OpenVPN](#62-openvpn)
   - [DHCP Server](#63-dhcp-server)
   - [DNS Server](#64-dns-server)
   - [IPsec VPN (StrongSwan)](#65-ipsec-vpn-strongswan)
7. [Crontab (Attività Pianificate)](#7-crontab-attività-pianificate)
8. [Log e Audit](#8-log-e-audit)
9. [Impostazioni](#9-impostazioni)
10. [Configurazioni Comuni](#10-configurazioni-comuni)

---

## 1. Accesso al Portale

Il portale è raggiungibile via browser all'indirizzo del server su porta **7443** (HTTPS). Il certificato è auto-firmato: il browser mostrerà un avviso di sicurezza che può essere ignorato accettando il rischio.

### Login

Inserire username e password nella schermata di accesso e premere **Accedi**.

**Credenziali impostate in fare di configurazione del servizio** 

### Autenticazione a due fattori (2FA)

Se l'account ha il 2FA attivo (o se è obbligatorio globalmente), dopo aver inserito le credenziali compare un secondo campo dove inserire il codice a 6 cifre generato dall'app di autenticazione (Google Authenticator, Authy o simili).

---

## 2. Dashboard

La dashboard è la schermata principale del portale e mostra una panoramica dello stato del sistema in tempo reale.

### Sezioni principali

| Elemento | Descrizione |
|----------|-------------|
| **CPU** | Percentuale di utilizzo del processore |
| **RAM** | Utilizzo della memoria, con valore totale e libero |
| **Disco** | Spazio occupato e disponibile |
| **Uptime** | Da quanto tempo il sistema è in esecuzione |
| **Traffico di rete** | Byte inviati e ricevuti per interfaccia |
| **Widget moduli** | Ogni modulo attivo può pubblicare i propri widget (es. client VPN connessi, lease DHCP attivi) |

Il grafico del traffico si aggiorna automaticamente. I dati storici vengono conservati per le ultime 24 ore.

---

## 3. Gestione Utenti

Accessibile dal menu laterale. La sezione è divisa in due parti: il proprio profilo e la gestione degli altri utenti (riservata agli amministratori).

### Il Mio Profilo

Ogni utente può modificare le proprie impostazioni di sicurezza indipendentemente dai permessi:

**Cambio password**
- Inserire la password attuale, la nuova password (minimo 6 caratteri) e confermarla.
- Premere **Salva Password**.

**Configurazione 2FA**
- Premere **Configura 2FA** per aprire il wizard.
- Inquadrare il QR code con l'app di autenticazione oppure inserire manualmente il codice segreto mostrato.
- Inserire il codice a 6 cifre generato dall'app per verificare la configurazione.
- Vengono forniti dei **codici di backup** da conservare in un posto sicuro: permettono l'accesso in caso di perdita del dispositivo.
- Per disattivare il 2FA, premere **Rimuovi 2FA** e confermare.

---

### Gestione Utenti (solo amministratori)

La tabella mostra tutti gli utenti del sistema con stato, data di creazione e permessi assegnati.

**Creare un nuovo utente**
1. Premere **Nuovo Utente**.
2. Compilare i campi:
   - **Username**: solo lettere, numeri, trattini e underscore (3–50 caratteri)
   - **Email**: indirizzo di posta opzionale
   - **Password**: minimo 6 caratteri
   - **Attivo**: se disattivato, l'utente non può accedere
   - **Superuser**: accesso completo a tutte le funzioni senza restrizioni
   - **Forza 2FA**: obbliga questo utente ad attivare il 2FA al prossimo accesso
3. Selezionare i **Permessi** assegnati (organizzati per sezione/modulo).
4. Premere **Salva**.

**Permessi disponibili (core)**

| Permesso | Accesso consentito |
|----------|-------------------|
| `users.view` | Visualizzare la lista utenti |
| `users.manage` | Creare, modificare, eliminare utenti |
| `firewall.view` | Visualizzare le regole firewall |
| `firewall.manage` | Aggiungere/modificare/eliminare regole |
| `network.view` | Visualizzare le interfacce di rete |
| `network.manage` | Configurare le interfacce di rete |
| `services.view` | Visualizzare lo stato dei servizi |
| `services.manage` | Avviare/fermare/riavviare i servizi |
| `settings.view` | Visualizzare le impostazioni |
| `settings.manage` | Modificare le impostazioni di sistema |
| `backup.view` | Scaricare backup |
| `backup.manage` | Creare, ripristinare, pianificare backup |
| `cron.view` | Visualizzare le attività pianificate |
| `cron.manage` | Aggiungere/modificare/eliminare attività |
| `audit.view` | Visualizzare i log di audit |
| `modules.view` | Visualizzare i moduli disponibili |
| `modules.manage` | Attivare/disattivare i moduli |

Ogni modulo aggiunge i propri permessi (es. `wireguard.view`, `dhcp.manage`, ecc.).

**Modificare un utente**: premere l'icona matita nella riga corrispondente.
**Disabilitare un utente**: usare il toggle nella riga (l'utente non potrà accedere ma i dati rimangono).
**Eliminare un utente**: icona cestino → confermare.
**Resettare il 2FA di un utente**: pulsante dedicato nel pannello di modifica.

---

## 4. Firewall

Il firewall gestisce le regole **iptables** della macchina. Le regole sono organizzate per **tabella** e **catena**, come in iptables standard.

### Tabelle e Catene

| Tabella | Catene disponibili | Utilizzo tipico |
|---------|-------------------|-----------------|
| **Filter** | INPUT, OUTPUT, FORWARD | Bloccare o permettere il traffico |
| **NAT** | PREROUTING, POSTROUTING | DNAT (port forwarding), SNAT, Masquerade |
| **Mangle** | INPUT, OUTPUT, FORWARD, PREROUTING, POSTROUTING | Modifica avanzata dei pacchetti |
| **Raw** | PREROUTING, OUTPUT | Escludere traffico dal connection tracking |

Selezionare la tabella in alto, poi la catena desiderata tramite i tab.

### Aggiungere una Regola

1. Selezionare tabella e catena.
2. Premere **Aggiungi Regola**.
3. Compilare i campi pertinenti (i campi non rilevanti possono essere lasciati vuoti):

**Campi comuni a tutte le tabelle:**

| Campo | Descrizione | Esempio |
|-------|-------------|---------|
| **Protocollo** | `tcp`, `udp`, `icmp`, `all` | `tcp` |
| **Sorgente** | IP o rete di provenienza (CIDR) | `192.168.1.0/24` |
| **Destinazione** | IP o rete di destinazione (CIDR) | `10.0.0.1` |
| **Porta** | Porta singola o range | `80` oppure `8000:9000` |
| **Commento** | Nota descrittiva interna | `Permetti HTTP da LAN` |

**Campi aggiuntivi per tabella Filter:**

| Campo | Descrizione |
|-------|-------------|
| **Stato** | Filtrare per stato connessione: `NEW`, `ESTABLISHED`, `RELATED`, `INVALID` |
| **Interfaccia In** | Interfaccia di ingresso del traffico (es. `eth1`) |
| **Interfaccia Out** | Interfaccia di uscita del traffico |
| **Azione** | `ACCEPT`, `DROP`, `REJECT`, `LOG` |

**Campi aggiuntivi per tabella NAT:**

| Campo | Descrizione | Utilizzo |
|-------|-------------|----------|
| **To Destination** | IP:Porta di destinazione (DNAT) | Port forwarding in entrata |
| **To Source** | IP sorgente da usare (SNAT) | Forzare uscita con IP specifico |
| **To Ports** | Porta di destinazione da remappare | Cambiare porta durante il NAT |
| **Azione** | `DNAT`, `SNAT`, `MASQUERADE`, `REDIRECT` | — |

**Azioni disponibili per tabella:**

| Tabella | Azioni |
|---------|--------|
| Filter | ACCEPT, DROP, REJECT, LOG |
| NAT | DNAT, SNAT, MASQUERADE, REDIRECT, ACCEPT |
| Mangle | MARK, TOS, TTL, ACCEPT |
| Raw | NOTRACK, ACCEPT |

### Ordinamento Regole

Le regole vengono applicate **dall'alto verso il basso**: la prima che fa match determina l'esito. Trascina le righe con il cursore di trascinamento per riordinarle. L'ordine viene salvato automaticamente.

### Anteprima iptables

La sezione **Anteprima** mostra la sintassi del comando `iptables` che verrà eseguito per la regola selezionata, utile per verifica.

### Import/Export

Le regole di una catena possono essere esportate in JSON e reimportate su un altro sistema tramite i pulsanti dedicati nell'intestazione.

---

## 5. Interfacce di Rete

Mostra tutte le interfacce fisiche del sistema con le loro statistiche in tempo reale.

### Informazioni visualizzate per interfaccia

- **Stato**: Attiva / Inattiva
- **Velocità**: in Mbps (se rilevata)
- **Tipo di configurazione**: badge DHCP o Statico (da netplan)
- **IP primario** e **IP secondari** (se presenti)
- **IPv6** (se presente)
- **MAC Address**
- **MTU**
- **Traffico**: byte e pacchetti inviati/ricevuti, contatori di errori

### Interfaccia WAN (eth0)

L'interfaccia WAN è in **sola lettura** — non può essere configurata dal portale. Eventuali IP secondari aggiunti dal sistema di autodeploy vengono visualizzati nella sezione "IP sec." della scheda.

### Configurare un'Interfaccia (interfacce non-WAN)

1. Premere l'icona ingranaggio sulla scheda dell'interfaccia.
2. Scegliere tra:
   - **DHCP**: l'interfaccia ottiene IP, gateway e DNS automaticamente
   - **Statico**: compilare IP (CIDR), gateway e DNS server
3. Opzionalmente impostare un MTU personalizzato.
4. Premere **Salva**.
5. Premere **Applica Netplan** (pulsante in alto) per attivare le modifiche.

> Le modifiche alla configurazione di rete vengono salvate in `/etc/netplan/` ma non attivate finché non si preme "Applica Netplan". Questa operazione potrebbe interrompere brevemente la connettività.

---

## 6. Moduli

I moduli sono componenti opzionali che estendono le funzionalità di MADMIN. Vanno prima **attivati** dalla sezione Moduli, poi compaiono nel menu laterale.

### Attivare/Disattivare un Modulo

1. Andare su **Moduli** nel menu laterale.
2. La lista mostra tutti i moduli disponibili con versione e stato.
3. Premere **Attiva** per abilitare un modulo — il sistema installerà le dipendenze necessarie e inizializzerà il database.
4. Premere **Disattiva** per disabilitare un modulo e rimuovere i suoi dati.

> La disattivazione è **irreversibile** per i dati: le configurazioni del modulo vengono eliminate.

---

### 6.1 WireGuard VPN

WireGuard è una VPN moderna, ad alte prestazioni, basata su crittografia a chiave pubblica.

#### Concetti base

- **Istanza**: un server WireGuard (interfaccia di rete `wg0`, `wg1`, ecc.)
- **Client**: un dispositivo che si connette al server
- **Tunnel Full**: tutto il traffico del client passa per la VPN (incluso accesso a internet)
- **Tunnel Split**: solo il traffico verso reti specifiche passa per la VPN

#### Creare un'Istanza

1. Premere **Nuova Istanza**.
2. Compilare:
   - **Nome**: identificatore dell'istanza
   - **Porta UDP**: porta di ascolto (predefinita: 51820)
   - **Subnet**: rete interna della VPN (es. `10.10.0.0/24`)
   - **Modalità tunnel**:
     - *Full Tunnel*: specificare i DNS da usare sul client
     - *Split Tunnel*: aggiungere le reti da instradare nella VPN e l'interfaccia locale di uscita
3. Premere **Crea**.

#### Gestire i Client

Aprire un'istanza per accedere alla gestione client:

- **Aggiungi Client**: genera automaticamente la coppia di chiavi e assegna un IP nella subnet della VPN
- **QR Code**: scansionare con l'app WireGuard per mobile (iOS/Android)
- **Scarica Config**: scarica il file `.conf` da importare nel client desktop
- **Invia config**: invia all'indirizzo email specificato un link per visualizzare/scaricare la configurazione.
- **Attiva/Disattiva**: il client disattivato non può connettersi senza eliminarlo
- **Elimina**: rimuove il client e la sua configurazione

#### Firewall (tab "Firewall" nell'istanza)

Ogni istanza WireGuard ha un proprio firewall che controlla cosa possono fare i client connessi. Il funzionamento è basato su **gruppi**: i client vengono assegnati a gruppi, e a ciascun gruppo si applicano regole specifiche.

**Policy predefinita**
In cima alla pagina si imposta il comportamento di default per tutti i client dell'istanza: **ACCEPT** (tutto permesso, regole usate per bloccare eccezioni) o **DROP** (tutto bloccato, regole usate per aprire eccezioni). La policy si applica quando nessuna regola di gruppo fa match.

**Gruppi**
Il pannello sinistro elenca i gruppi creati, ciascuno con il numero di client membri e il numero di regole configurate. I gruppi possono essere trascinati per cambiare la priorità: i gruppi in alto vengono valutati per primi.

- **Nuovo gruppo**: crea un gruppo con nome e descrizione
- **Aggiungi client al gruppo**: selezionare client non ancora assegnati ad altri gruppi
- **Rimuovi client dal gruppo**: premere la X sul badge del client

**Regole del gruppo**
Per ciascun gruppo, il pannello destro mostra le regole associate. Le regole vengono valutate nell'ordine mostrato (trascinare per riordinare).

Campi della regola:

| Campo | Opzioni | Note |
|-------|---------|------|
| **Azione** | ACCEPT / DROP | Cosa fare quando la regola fa match |
| **Protocollo** | Tutti / TCP / UDP / ICMP | — |
| **Destinazione** | CIDR (es. `10.0.0.0/24`) | Default `0.0.0.0/0` (ovunque) |
| **Porta** | Numero porta (es. `443`) | Solo per TCP/UDP |
| **Descrizione** | Testo libero | Nota interna |

---

### 6.2 OpenVPN

OpenVPN è una VPN tradizionale basata su certificati, compatibile con un'ampia gamma di dispositivi.

#### Differenze rispetto a WireGuard

- Supporta sia **UDP** che **TCP** (utile quando UDP è bloccato)
- Usa un sistema PKI (autorità certificante interna)
- Leggermente più lento ma più compatibile con ambienti restrittivi

#### Creare un'Istanza

1. Premere **Nuova Istanza**.
2. Compilare:
   - **Nome**: identificatore
   - **Porta**: porta di ascolto (predefinita: 1194)
   - **Protocollo**: UDP (consigliato) o TCP
   - **Subnet**: rete interna VPN (es. `10.8.0.0/24`)
   - **Endpoint**: IP pubblico o dominio del server (si può rilevare automaticamente)
   - **Modalità tunnel**: Full o Split (come WireGuard)
   - **Avanzate**: cifrario crittografico, durata certificati client

#### Gestire i Client

Uguale a WireGuard: aggiunta client, download configurazione (file `.ovpn`), abilitazione/disabilitazione, eliminazione.

#### Firewall (tab "Firewall" nell'istanza)

Il firewall di OpenVPN è strutturalmente identico a quello di WireGuard: stessa logica di gruppi, stessa policy predefinita per istanza, stesse opzioni di regola.

**Differenza pratica:** i client revocati (certificato revocato) non sono selezionabili come membri di un gruppo.

Per il funzionamento dettagliato di policy, gruppi e regole, fare riferimento alla sezione [Firewall WireGuard](#firewall-tab-firewall-nellistanza) — il comportamento è identico.

---

### 6.3 DHCP Server

Gestisce l'assegnazione automatica di indirizzi IP ai dispositivi della rete locale.

#### Dashboard DHCP

Mostra lo stato del servizio, il numero di subnet configurate, le prenotazioni statiche e i lease attivi.

#### Creare una Subnet

1. Premere **Nuova Subnet**.
2. Compilare:
   - **Nome**: etichetta descrittiva
   - **Interfaccia**: interfaccia di rete su cui il DHCP è attivo
   - **Rete**: indirizzo di rete in CIDR (es. `192.168.1.0/24`)
   - **Range**: IP iniziale e finale del pool dinamico (es. `192.168.1.100` → `192.168.1.200`)
   - **Gateway**: IP del router/gateway predefinito
   - **DNS**: server DNS da comunicare ai client (es. `8.8.8.8, 1.1.1.1`)
   - **Dominio**: suffisso DNS opzionale (es. `azienda.local`)
   - **Lease time**: durata dell'assegnazione IP in secondi (predefinito: 86400 = 24h)

#### Prenotazioni Statiche (IP fissi per MAC)

All'interno di una subnet, nella scheda **Prenotazioni**:
1. Premere **Aggiungi Prenotazione**.
2. Inserire il **MAC address** del dispositivo e l'**IP** da assegnare sempre.
3. Il dispositivo riceverà sempre lo stesso IP anche usando DHCP.

#### Lease Attivi

La scheda **Lease** mostra i dispositivi attualmente connessi con IP assegnato, MAC, hostname e scadenza del lease.

#### Applicare la Configurazione

Dopo ogni modifica premere **Applica Configurazione** — il servizio DHCP viene riavviato con la nuova configurazione.

---

### 6.4 DNS Server

Gestisce un server DNS interno basato su BIND9, utile per risolvere nomi interni o fare da resolver per la rete locale.

#### Modalità operative

| Modalità | Descrizione |
|----------|-------------|
| **Ricorsivo** | Risolve qualsiasi dominio interrogando i root server (funziona da resolver completo) |
| **Solo Forwarder** | Gira le query a server DNS upstream configurati (es. 8.8.8.8) |
| **Non Ricorsivo** | Risponde solo alle zone configurate localmente |

#### Creare una Zona

1. Andare su **Zone** → **Nuova Zona**.
2. Scegliere il tipo:
   - **Master**: zona autoritativa gestita localmente (per domini interni)
   - **Forward**: delega le query per un dominio a server DNS specifici
3. Inserire il nome della zona (es. `azienda.local`) e una descrizione opzionale.

#### Gestire i Record DNS

All'interno di una zona:

| Tipo Record | Utilizzo |
|-------------|----------|
| **A** | Nome → IPv4 (es. `server` → `192.168.1.10`) |
| **AAAA** | Nome → IPv6 |
| **CNAME** | Alias (es. `www` → `server.azienda.local`) |
| **MX** | Mail server per il dominio |
| **TXT** | Record testuale (SPF, DKIM, ecc.) |
| **PTR** | Risoluzione inversa (IP → Nome) |
| **NS** | Name server autoritativo |
| **SRV** | Localizzazione servizi |

Per ogni record: Nome, Valore/Dato, TTL (time to live in secondi).

#### Test DNS

La scheda **Test** permette di interrogare il server DNS locale digitando un nome e selezionando il tipo di record, utile per verificare che le zone siano configurate correttamente.

---

### 6.5 IPsec VPN (StrongSwan)

IPsec è una VPN progettata per connessioni **site-to-site** stabili e permanenti tra due sedi/router, spesso usata per collegare due reti aziendali.

#### Differenze rispetto a WireGuard/OpenVPN

- Non pensata per client mobili, ma per tunnel fissi tra router/firewall
- Standard di interoperabilità elevato (compatibile con apparati Cisco, Fortinet, MikroTik, ecc.)
- Negoziazione automatica delle chiavi (IKEv1 o IKEv2)

#### Creare un Tunnel

1. Premere **Nuovo Tunnel**.
2. Compilare:
   - **Nome**: identificatore del tunnel
   - **Rete locale**: subnet locale da esporre nel tunnel (es. `192.168.1.0/24`)
   - **Rete remota**: subnet dall'altro lato del tunnel (es. `10.0.0.0/24`)
   - **Gateway remoto**: IP pubblico dell'altro router/firewall
   - **Versione IKE**: IKEv2 (consigliato) o IKEv1 (compatibilità legacy)
   - **Autenticazione**: PSK (chiave condivisa) o Certificato
   - **Suite crittografica**: algoritmi di cifratura fase 1 e fase 2

#### Stato e Gestione

- Il tunnel può essere avviato/fermato manualmente
- La sezione **SA** (Security Associations) mostra le associazioni di sicurezza attive e le statistiche di traffico

#### Firewall (sezione "Firewall" nel dettaglio tunnel)

Il firewall IPsec controlla il traffico all'interno di ciascun tunnel, separando le regole per direzione. A differenza di WireGuard e OpenVPN (dove si ragiona per client/gruppo), qui si lavora per **Child SA** (fase 2 del tunnel, che corrisponde a una coppia di subnet locali/remote).

Se il tunnel ha più Child SA, appaiono tab separati con l'etichetta `rete-locale → rete-remota`.

**Per ogni Child SA esistono due sezioni indipendenti:**

- **Regole Outbound** (locale → remoto): traffico che parte dalla rete locale verso la rete remota
- **Regole Inbound** (remoto → locale): traffico che arriva dalla rete remota verso la rete locale

Ciascuna sezione ha la propria **policy predefinita** (ACCEPT o DROP) indipendente dall'altra.

**Campi della regola:**

| Campo | Opzioni | Note |
|-------|---------|------|
| **Direzione** | Outbound / Inbound / Entrambe | In quale direzione applicare la regola |
| **Azione** | ACCEPT / DROP | Permetti o blocca |
| **Protocollo** | Tutti / TCP / UDP / ICMP | — |
| **Porta** | Es. `80` oppure `8000-8100` | Solo per TCP/UDP; range con trattino |
| **Sorgente** | CIDR (es. `192.168.1.0/24`) | Lasciare vuoto per usare la subnet del tunnel |
| **Destinazione** | CIDR (es. `10.0.0.0/24`) | Lasciare vuoto per usare la subnet del tunnel |
| **Descrizione** | Testo libero | Nota interna |

Le regole sono riordinabili con drag-and-drop: vengono valutate dall'alto verso il basso e vince la prima che fa match.

**Esempio pratico:** bloccare l'accesso SSH (porta 22) dalla rete remota verso la rete locale, permettendo tutto il resto:

1. Policy Inbound → **ACCEPT**
2. Regola: Direzione `Inbound`, Azione `DROP`, Protocollo `TCP`, Porta `22`
3. Posizionare la regola DROP sopra qualsiasi regola ACCEPT più generica

---

## 7. Crontab (Attività Pianificate)

Permette di pianificare l'esecuzione automatica di comandi di sistema a intervalli regolari.

### Aggiungere un'Attività

1. Premere **Nuova Attività**.
2. Definire la **pianificazione** con una delle due modalità:
   - **Preset**: selezionare dall'elenco (ogni minuto, ogni ora, ogni giorno a mezzanotte, settimanale, mensile, ecc.)
   - **Manuale**: compilare i 5 campi cron:
     ```
     Minuto  Ora  Giorno  Mese  GiornoSettimana
     *       *    *       *     *
     ```
     Il simbolo `*` significa "sempre". Esempi:
     - `0 2 * * *` → ogni giorno alle 02:00
     - `*/15 * * * *` → ogni 15 minuti
     - `0 0 1 * *` → il primo di ogni mese a mezzanotte
3. Inserire il **Comando** da eseguire (percorso assoluto consigliato, es. `/usr/bin/script.sh`).
4. Abilitare o disabilitare l'attività con il toggle.
5. Premere **Salva**.

La pianificazione viene mostrata in forma leggibile (es. "Ogni giorno alle 02:00") nell'elenco.

---

## 8. Log e Audit

La sezione Log fornisce due viste complementari per monitorare le attività sul sistema.

### Log di Audit

Registra tutte le operazioni effettuate tramite il portale (chi ha fatto cosa e quando).

**Filtri disponibili:**
- **Categoria**: Solo scritture (creazione/modifica/eliminazione), Tutte le operazioni, Solo letture
- **Utente**: filtrare per specifico utente
- **Ricerca**: parola chiave nel percorso API
- **Periodo**: data di inizio e fine

**Colonne:**
- Timestamp
- Utente
- Operazione (metodo HTTP + percorso)
- Codice risposta (verde = successo, rosso = errore)
- Durata in millisecondi
- IP del client

Premere su una riga per visualizzare il **payload** della richiesta (dati inviati) o i dettagli dell'errore se presente.

**Esporta CSV**: scarica i log filtrati in formato foglio di calcolo.

---

### Log di Sistema

Mostra i log del servizio MADMIN in tempo reale (equivalente a `journalctl`).

**Opzioni:**
- **Righe**: quante righe mostrare (100 / 200 / 500 / 1000)
- **Filtro**: cerca testo specifico nei log
- **Nascondi AUDIT**: nasconde le righe di audit per vedere solo eventi di sistema

**Colori:**
- Rosso: errori critici
- Arancione: avvisi
- Ciano: log di audit
- Grigio scuro: log di accesso HTTP

---

## 9. Impostazioni

Configurazioni globali del portale. Alcune richiedono il permesso `settings.manage`.

### Personalizzazione

- **Nome azienda**: testo mostrato nel menu e nell'intestazione (predefinito: MADMIN)
- **Colore primario**: colore dell'interfaccia (picker cromatico), propagato via variabile CSS
- **Tema**: chiaro o scuro (Dark Mode)

### Backup

- **Esporta backup**: scarica un archivio con la configurazione del sistema (database + file di configurazione)
- **Importa backup**: ripristina una configurazione da un file di backup precedente
- **Backup pianificati**: configura backup automatici giornalieri, settimanali o mensili con destinazione locale o remota (S3, FTP)

### Sicurezza

- **2FA obbligatoria globalmente**: se attivo, tutti gli utenti devono configurare il 2FA
- **Durata token**: minuti di validità della sessione (predefinito: 720 = 12h)

### Audit

- **Retention log**: quanti giorni conservare i log di audit (i log più vecchi vengono eliminati automaticamente)

---

## 10. Configurazioni Comuni

Questa sezione illustra come realizzare configurazioni tipiche usando il firewall del portale.

---

### 10.1 DNAT — Port Forwarding (traffico in entrata)

**Scenario:** si vuole che le connessioni che arrivano sull'IP pubblico della macchina sulla porta 8080 vengano indirizzate a un server interno `192.168.1.10` sulla porta 80.

**Dove configurarlo:** Tabella **NAT** → Catena **PREROUTING**

**Impostazioni della regola:**

| Campo | Valore |
|-------|--------|
| Protocollo | `tcp` |
| Porta | `8080` |
| Azione | `DNAT` |
| To Destination | `192.168.1.10:80` |

**Effetto:** chi si connette all'IP del server sulla porta 8080 viene trasparentemente reindirizzato al server interno. Il chiamante non si accorge del reindirizzamento.

> Per rendere funzionale il DNAT è spesso necessaria anche una regola in **Filter → FORWARD** che permetta il traffico verso `192.168.1.10:80`.

---

### 10.2 SNAT — Cambiare l'IP sorgente in uscita

**Scenario A — IP specifico per una macchina interna:** si vuole che il traffico proveniente da `192.168.1.50` esca su internet con l'IP secondario `1.2.3.4` invece di quello principale.

**Dove configurarlo:** Tabella **NAT** → Catena **POSTROUTING**

**Impostazioni della regola:**

| Campo | Valore |
|-------|--------|
| Protocollo | (lasciare vuoto = tutti) |
| Sorgente | `192.168.1.50` |
| Interfaccia Out | `eth0` |
| Azione | `SNAT` |
| To Source | `1.2.3.4` |

**Scenario B — IP specifico per una VPN:** si vuole che tutto il traffico proveniente dall'interfaccia WireGuard `wg0` esca con l'IP secondario `1.2.3.4`.

| Campo | Valore |
|-------|--------|
| Interfaccia In | `wg0` |
| Interfaccia Out | `eth0` |
| Azione | `SNAT` |
| To Source | `1.2.3.4` |

> L'IP indicato in "To Source" deve essere già assegnato all'interfaccia WAN. Gli IP secondari aggiunti automaticamente sono visibili nella sezione [Interfacce di Rete](#5-interfacce-di-rete).

---

### 10.3 Masquerade — NAT dinamico per la LAN

**Scenario:** i dispositivi della rete interna `192.168.1.0/24` devono uscire su internet usando l'IP pubblico del server (IP dinamico o comunque non fisso).

**Dove configurarlo:** Tabella **NAT** → Catena **POSTROUTING**

| Campo | Valore |
|-------|--------|
| Sorgente | `192.168.1.0/24` |
| Interfaccia Out | `eth0` |
| Azione | `MASQUERADE` |

**Differenza tra MASQUERADE e SNAT:** MASQUERADE usa automaticamente l'IP corrente dell'interfaccia di uscita, utile se l'IP pubblico può cambiare. SNAT richiede di specificare l'IP esplicitamente ed è leggermente più performante se l'IP è fisso.

---

### 10.4 Bloccare un IP o una Rete

**Scenario:** bloccare tutto il traffico in ingresso proveniente dall'IP `1.2.3.4`.

**Dove configurarlo:** Tabella **Filter** → Catena **INPUT**

| Campo | Valore |
|-------|--------|
| Sorgente | `1.2.3.4` |
| Azione | `DROP` |

> Mettere questa regola **prima** di eventuali regole permissive più generiche, altrimenti non verrà applicata.

---

### 10.5 Permettere solo porte specifiche in ingresso

**Scenario:** permettere solo SSH (porta 22) e HTTPS (porta 443) dall'esterno, bloccare tutto il resto.

**Dove configurarlo:** Tabella **Filter** → Catena **INPUT**

Regola 1 — Permetti traffico già stabilito:

| Campo | Valore |
|-------|--------|
| Stato | `ESTABLISHED,RELATED` |
| Azione | `ACCEPT` |

Regola 2 — Permetti SSH:

| Campo | Valore |
|-------|--------|
| Protocollo | `tcp` |
| Porta | `22` |
| Azione | `ACCEPT` |

Regola 3 — Permetti HTTPS:

| Campo | Valore |
|-------|--------|
| Protocollo | `tcp` |
| Porta | `443` |
| Azione | `ACCEPT` |

Regola 4 — Blocca tutto il resto:

| Campo | Valore |
|-------|--------|
| (nessun filtro) | — |
| Azione | `DROP` |

> L'ordine è fondamentale: la regola DROP deve essere l'ultima.

---

*Documento generato per MADMIN — Sistema di amministrazione modulare per Ubuntu 24.04*
