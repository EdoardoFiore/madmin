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
   - [Reverse Proxy](#66-reverse-proxy)
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

Se l'account ha il 2FA attivo (o se è obbligatorio globalmente), dopo aver inserito le credenziali compare un secondo campo dove inserire il codice a 6 cifre generato dall'app di autenticazione (Google Authenticator, Authy o simili), oppure uno dei codici di backup (12 caratteri).

Dopo troppi tentativi falliti l'accesso viene bloccato temporaneamente (per indirizzo e per utente).

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
- Inserire la password attuale, la nuova password e confermarla. La password deve avere almeno 8 caratteri, una lettera maiuscola, una cifra e un carattere speciale.
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
   - **Password**: almeno 8 caratteri, con una maiuscola, una cifra e un carattere speciale
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
| `permissions.manage` | Assegnare i permessi agli utenti (richiede `users.manage`) |
| `firewall.view` | Visualizzare le regole firewall |
| `firewall.manage` | Aggiungere/modificare/eliminare regole, oggetti e IP Pool |
| `network.view` | Visualizzare le interfacce di rete |
| `network.manage` | Configurare le interfacce di rete |
| `settings.view` | Visualizzare personalizzazione, porta di gestione e certificato SSL |
| `settings.manage` | Modificare personalizzazione, porta di gestione e certificato SSL |
| `smtp.view` | Visualizzare la configurazione SMTP |
| `smtp.manage` | Modificare la configurazione SMTP e inviare email di test |
| `backup.view` | Visualizzare impostazioni, storico e archivi di backup |
| `backup.manage` | Configurare i backup, esportare, scaricare ed eliminare archivi |
| `backup.restore` | Importare/ripristinare un archivio (contiene utenti e hash delle password: equivale ad accesso da superuser) |
| `cron.view` | Visualizzare le attività pianificate (modificarle è riservato ai superuser) |
| `services.manage` | Avviare/fermare/riavviare i servizi |
| `modules.view` | Visualizzare i moduli installati |
| `modules.manage` | Attivare/disattivare e configurare i moduli |
| `logs.view` | Visualizzare i log di audit e di sistema |

Ogni modulo aggiunge i propri permessi (es. `wireguard.view`, `dhcp.manage`, ecc.).

**Modificare un utente**: premere l'icona matita nella riga corrispondente.
**Disabilitare un utente**: usare il toggle nella riga (l'utente non potrà accedere ma i dati rimangono).
**Eliminare un utente**: icona cestino → confermare.
**Resettare il 2FA di un utente**: pulsante dedicato nel pannello di modifica.

---

## 4. Firewall

Il firewall gestisce le regole **iptables** della macchina. La pagina offre tre viste, selezionabili in alto:

| Vista | Per cosa |
|-------|----------|
| **Standard** | Uso quotidiano: regole di forward (come navigano e comunicano le reti collegate) e port forwarding, in stile FortiGate |
| **Avanzata** | Tutte le tabelle e catene iptables, comprese le regole verso la macchina stessa (INPUT) e le regole NAT personalizzate |
| **Oggetti** | Indirizzi, gruppi di indirizzi e IP Pool riutilizzabili nelle regole |

La vista scelta tra Standard e Avanzata viene ricordata per l'utente. In entrambe sono disponibili **Simula pacchetto** e **Cattura traffico**; in Avanzata anche **Anteprima iptables**.

### Come viene valutato il traffico

- Le connessioni **già stabilite** sono sempre accettate per prime: una regola nuova o modificata vale solo per le connessioni nuove (vedi [Connessioni già aperte](#connessioni-già-aperte)).
- Le catene dei **moduli** (WireGuard, OpenVPN, IPsec, DNS) vengono valutate prima delle regole del firewall.
- **Forward** (traffico che attraversa la macchina): le regole sono raggruppate per coppia di interfacce *ingresso → uscita*. I gruppi vengono valutati nell'ordine in cui sono elencati, le regole di ogni gruppo dall'alto verso il basso: la prima che corrisponde decide. Seguono le **regole automatiche** dei port forward e infine il **Nega implicito**, che blocca tutto ciò che nessuna regola ha consentito.
- **Ingresso** (traffico verso la macchina stessa, catena INPUT, gestita in Avanzata): prima le regole automatiche dei port forward che puntano alla macchina, poi le regole nell'ordine; l'ultima regola predefinita blocca tutto il resto.

Il numero **#** accanto a ogni regola è la sua posizione reale nell'ordine di valutazione.

### Vista Standard

#### Regole firewall (forward)

Premere **Nuova regola** per aprire l'editor nel pannello laterale. Campi:

| Campo | Descrizione |
|-------|-------------|
| **Nome** | Etichetta descrittiva (opzionale) |
| **Interfaccia di ingresso / uscita** | Da dove arriva e da dove esce il traffico; *qualsiasi* se vuoto. Le due interfacce devono essere diverse |
| **Sorgente / Destinazione** | Scrivere un IP, una subnet CIDR o un intervallo (`10.0.0.1-10.0.0.20`) e premere Invio, oppure cliccare il campo e scegliere oggetti e gruppi dal pannello **Seleziona voci** a destra (dove si possono anche creare). Vuoto = qualsiasi |
| **Servizio** | Protocollo (tutti, TCP, UDP, ICMP), porta (singola, lista `80,443` o intervallo `8000:8080`) o un preset |
| **Azione** | **Consenti** o **Nega** |
| **NAT** | Solo con *Consenti*: il traffico esce con un indirizzo della macchina. Per una regola nuova si attiva da solo quando l'interfaccia di uscita è la WAN (rotta di default) |
| **IP di uscita** | Con il NAT attivo: l'IP dell'interfaccia di uscita (automatico), un altro indirizzo configurato su quell'interfaccia, oppure un IP Pool |
| **Regola attiva** | Una regola disattivata resta in elenco e mantiene il suo posto |

Un indirizzo scritto a mano, se sono più di uno o è un intervallo, viene salvato come oggetto indirizzo (visibile in **Oggetti**).

Se una regola con NAT non indica l'interfaccia di uscita, il NAT si applica solo al traffico che esce dalla rotta di default: la colonna NAT lo indica con *→ eth0*.

**Ordinare le regole**
- Trascinare una riga per spostarla nel suo gruppo, oppure usare il menu **⋮ → Sposta su / Sposta giù**.
- Trascinare l'intestazione di un gruppo per cambiare l'ordine dei gruppi. Il badge *valutato dopo N* indica che gruppi precedenti possono decidere lo stesso traffico (es. *eth1 → qualsiasi* prima di *eth1 → eth0*).

**Badge sulle regole**

| Badge | Significato |
|-------|-------------|
| *Mai raggiunta (#n)* | Una regola più in alto prende la decisione opposta su tutto il suo traffico: questa non ha effetto. Lo stesso badge compare se la regola più in alto accetta il traffico con un NAT diverso |
| *Duplicata di #n* / *Già coperta da #n* | Una regola più in alto prende già la stessa decisione |
| *Avanzata* | La regola ha condizioni visibili solo in Avanzata (stato, rate limit, log), conservate al salvataggio |
| *IP assente* | L'IP di uscita del NAT non è più configurato sull'interfaccia: le risposte non tornano |
| *NAT sostituito (#n Advanced)* | Una regola NAT personalizzata di Avanzata, valutata prima, natta diversamente questo traffico |

Accanto a ogni regola sono mostrati il traffico totale e un grafico delle ultime 24 ore; passando sopra l'icona compaiono pacchetti e date di primo e ultimo utilizzo.

In fondo all'elenco:
- **Regole automatiche di forward**: create dal sistema per i port forward e per l'hairpin NAT, non modificabili. Una regola *Nega* più in alto che copre il loro traffico le rende inefficaci (badge *Mai raggiunta*).
- **Nega implicito**: sempre ultimo.

Le regole NAT personalizzate create in Avanzata non compaiono qui: una riga ne segnala la presenza.

#### Port Forwarding

Inoltra una porta esterna verso un host interno. Premere **Nuovo port forward**:

| Campo | Descrizione |
|-------|-------------|
| **Interfaccia di ingresso** | Proposta la WAN. Obbligatoria se non si indica l'IP esterno |
| **Protocollo / Porta esterna** | TCP o UDP; porta obbligatoria (singola, lista o intervallo) |
| **IP esterno** | Opzionale con l'interfaccia indicata: lega il forward a uno specifico IP pubblico (utile con più IP sulla WAN) |
| **IP interno / Porta interna** | Destinazione del traffico; porta interna vuota = stessa porta. In alternativa all'IP, un oggetto indirizzo host (CIDR /32) |
| **Sorgente** | Limita il forward a determinati indirizzi di origine (opzionale) |
| **NAT hairpin** | Permette ai client LAN di raggiungere il forward usando l'IP pubblico |

Non è possibile salvare un port forward senza interfaccia di ingresso né IP esterno: intercetterebbe anche il traffico dei client LAN verso Internet su quella porta (es. un forward della 443 prenderebbe la loro navigazione HTTPS). Le porte usate dal pannello e dai servizi MADMIN non possono essere inoltrate.

Il traffico inoltrato viene consentito automaticamente (regole automatiche di forward). Badge:
- *Bloccato da #n*: la regola *Nega* #n blocca tutto il traffico del forward prima che venga accettato; spostarla, restringerla o aggiungere sopra una regola che lo consenta.
- *Senza interfaccia né IP esterno*: forward ripristinato da una configurazione precedente a questo controllo; indicare l'interfaccia WAN o l'IP esterno.

#### Connessioni già aperte

Le connessioni stabilite continuano anche dopo una modifica delle regole. Dopo il salvataggio MADMIN propone di chiuderle quando:
- si attiva una regola *Nega*: le connessioni che quella regola ora blocca;
- si disattiva, elimina o restringe una regola *Consenti*: le connessioni che consentiva e che nessuna regola accetta più;
- cambia il NAT di una regola: le sue connessioni, che altrimenti mantengono il vecchio indirizzo di uscita.

Prima di chiudere viene mostrata un'anteprima. Restano sempre aperte le connessioni del proprio browser, quelle accettate da un'altra regola e quelle che dipendono da oggetti non risolti. Le catene dei moduli non sono simulate: controllare l'anteprima se la regola copre anche traffico VPN.

### Vista Avanzata

Mostra tutte le regole per **tabella** e **catena**, come in iptables:

| Tabella | Catene | Utilizzo tipico |
|---------|--------|-----------------|
| **Filter** | INPUT, OUTPUT, FORWARD | Consentire o bloccare il traffico |
| **NAT** | PREROUTING, POSTROUTING, OUTPUT | Port forwarding, SNAT, Masquerade, Redirect |
| **Mangle** | PREROUTING, INPUT, FORWARD, OUTPUT, POSTROUTING | Modifica avanzata dei pacchetti |
| **Raw** | PREROUTING, OUTPUT | Escludere traffico dal connection tracking |

Oltre ai campi della vista Standard, l'editor offre: stato della connessione, rate limit, log (prefisso e livello), tipo di REJECT, To Ports (REDIRECT/MASQUERADE), SNAT verso un indirizzo o un IP Pool.

| Tabella | Azioni |
|---------|--------|
| Filter | ACCEPT, DROP, REJECT, LOG, RETURN |
| NAT | DNAT, SNAT, MASQUERADE, REDIRECT, ACCEPT, RETURN |
| Mangle | MARK, TOS, TTL, ACCEPT, RETURN |
| Raw | NOTRACK, ACCEPT, RETURN |

- La catena **FORWARD** è raggruppata per coppia di interfacce come nella vista Standard.
- Le regole automatiche (port forward, NAT delle regole, hairpin) compaiono con il lucchetto e il badge *Auto*.
- Le regole **NAT/POSTROUTING** personalizzate vengono valutate prima del NAT delle regole di forward: servono per le eccezioni.
- Le regole si riordinano trascinandole.
- **Accesso Gateway**: quali reti LAN possono raggiungere gli indirizzi della macchina sulle altre interfacce.
- **Esporta / Importa**: le regole in JSON, in aggiunta o in sostituzione di quelle esistenti. Le regole non valide vengono saltate e segnalate.

### Oggetti

- **Indirizzi**: CIDR (IP singolo o subnet), Intervallo, FQDN (risolto e aggiornato ogni notte), Paese (liste geo-IP, aggiornate ogni notte).
- **Gruppi**: insiemi di indirizzi, usabili come un singolo oggetto.
- **IP Pool**: indirizzi con cui le regole possono nattare il traffico in uscita.
  - *Overload*: un IP o un intervallo (massimo 256 indirizzi); più client condividono gli indirizzi e ognuno esce sempre con lo stesso.
  - *One-to-one*: una subnet CIDR grande quanto la sorgente della regola; ogni host esce con l'indirizzo corrispondente.
  - *Rispondi ARP*: MADMIN aggiunge gli indirizzi all'interfaccia della loro subnet, così il router del provider li raggiunge; nessun servizio della macchina risponde su questi IP. Da disattivare se il provider instrada il blocco direttamente alla macchina. Non usare indirizzi assegnati ad altri dispositivi della stessa rete.

Un oggetto modificato aggiorna subito tutte le regole che lo usano.

### Simula pacchetto

Indica quale regola decide una nuova connessione. Inserire protocollo, IP sorgente e destinazione, porta ed eventualmente le interfacce (altrimenti dedotte dalla tabella di routing). Il risultato mostra l'eventuale port forward applicato, la catena, ogni regola valutata con l'esito, la regola che decide e, per il traffico consentito in uscita, l'indirizzo con cui esce. Le catene dei moduli non sono simulate.

### Anteprima iptables

Solo in Avanzata: il ruleset che MADMIN carica con iptables-restore, diviso per tabella e filtrabile. Non applica nessuna modifica.

### Cattura traffico

Mostra a schermo, in tempo reale, i pacchetti che passano per un'interfaccia (tcpdump), per il troubleshooting. Si apre con il pulsante **Cattura traffico** in alto, nella vista Standard e in Avanzata, oppure dalla riga di una regola (menu **⋮** in Standard, icona radar in Avanzata) con i campi già compilati dalla regola. Richiede il permesso `firewall.manage`.

> La cattura mostra il contenuto dei pacchetti: il traffico non cifrato, credenziali comprese, è leggibile. Ogni avvio viene registrato nell'audit log con interfaccia e filtri.

**Filtri** (tutti in AND):

| Campo | Descrizione |
|-------|-------------|
| **Interfaccia** | Una interfaccia (anche VPN, es. `wg0`, `tun0`) o *Tutte (any)* |
| **Protocollo** | TCP, UDP, ICMP, ARP o tutti |
| **Porta** | Porta sorgente o destinazione |
| **Host / Sorgente / Destinazione** | Un indirizzo IPv4 in entrambe le direzioni, solo come mittente o solo come destinatario |
| **Rete** (opzioni avanzate) | Una subnet CIDR |
| **Filtro BPF aggiuntivo** (opzioni avanzate) | Espressione in sintassi tcpdump, es. `not port 22` o `icmp or arp`. Viene verificata prima di avviare |

Opzioni avanzate: durata massima (default 60 s, massimo 600), pacchetti massimi (default 1000, massimo 100000), byte per pacchetto, indirizzi MAC (`-e`), dettagli (`-v`). **Escludi il traffico di questo pannello** è attivo di default: senza, catturando l'interfaccia da cui si accede al pannello si vedrebbe anche lo stream della cattura stessa.

**Durante la cattura**
- **Ferma** termina la cattura; **Pausa** congela lo schermo, mentre i pacchetti continuano ad arrivare e vengono mostrati alla ripresa.
- Il campo sopra l'output mostra solo le righe che contengono il testo scritto; **Pulisci** svuota lo schermo.
- La barra di stato mostra pacchetti, tempo trascorso, filtro applicato e, a fine cattura, il motivo (durata, numero di pacchetti, dimensione massima, fermata).
- A schermo arrivano al massimo 200 righe al secondo: le altre vengono contate come *non mostrate* e restano nel file pcap.

**A fine cattura**
- **Scarica testo**: le righe ricevute, in un file di testo.
- **Scarica pcap**: il file completo da aprire in Wireshark (massimo 50 MB). Resta disponibile per 30 minuti e viene eliminato a ogni riavvio del servizio.

Ogni utente ha una cattura alla volta (avviarne un'altra chiude la precedente) e sulla macchina ne girano al massimo tre insieme. Chiudendo il pannello o cambiando pagina la cattura si ferma.

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

### 6.6 Reverse Proxy

Il modulo Reverse Proxy gestisce un server nginx come proxy inverso per esporre servizi interni su internet (o sulla rete locale) con supporto a SSL/TLS automatico (Let's Encrypt), autenticazione HTTP e controllo accessi per IP.

> **Prerequisito:** il modulo occupa le porte **80** e **443** del sistema. Se un altro servizio (o regola DNAT) le usa già, l'attivazione viene bloccata e viene mostrato un avviso con i dettagli del conflitto.

#### Concetti base

| Termine | Descrizione |
|---------|-------------|
| **Proxy Host** | Regola di proxy: uno o più domini sorgente → un backend |
| **Backend** | Servizio interno a cui il traffico viene inoltrato (IP:porta) |
| **Lista di Accesso** | Policy riutilizzabile di autenticazione e/o regole IP |
| **Certificato** | Certificato TLS Let's Encrypt associato a un Proxy Host |

L'interfaccia è divisa in tre tab: **Proxy Hosts**, **Liste di Accesso**, **Certificati SSL/TLS**.

#### Stato del servizio

In cima alla pagina è visibile un badge con lo stato nginx (**Attivo** / **Inattivo**). Se il modulo è stato bloccato a causa di un conflitto su porta 80/443, appare un banner arancione con la spiegazione.

---

#### Proxy Hosts

##### Creare un Proxy Host

1. Premere **Nuovo Host**.
2. Nel tab **Dettagli**:
   - **Domini sorgente**: uno o più nomi di dominio (es. `app.esempio.com`). Inserire e premere Invio o virgola per aggiungerne più di uno.
   - **Schema**: `http` o `https` (protocollo verso il backend).
   - **Host/IP backend**: indirizzo del servizio interno.
   - **Porta backend**: porta del servizio interno (1–65535).
   - **Lista di Accesso**: selezionare una lista preconfigurata oppure lasciare "Pubblica".
   - **HTTP/2**: abilita HTTP/2 sul listener HTTPS.
   - **Blocca exploit**: blocca percorsi pericolosi (`../, .git, .env, /wp-admin, /xmlrpc.php`).
   - **WebSocket**: aggiunge gli header necessari per connessioni WebSocket.
   - **Cache**: abilita il bypass della cache Nginx.
3. Nel tab **SSL**:
   - Se non esiste ancora un certificato, premere **Richiedi certificato Let's Encrypt** per ottenerne uno automaticamente.
   - Dopo l'emissione è possibile abilitare **Forza HTTPS** (redirect automatico da HTTP).
4. Nel tab **Avanzate**: inserire configurazione nginx personalizzata (snippet libero, aggiunto in fondo al blocco `location /`).
5. Premere **Salva**.

##### Gestire i Proxy Host

| Azione | Descrizione |
|--------|-------------|
| **Modifica** (matita) | Apre il form di modifica |
| **Abilita / Disabilita** | Attiva o rimuove il vhost da nginx senza eliminarlo |
| **Richiedi / Rinnova cert** | Emette o rinnova il certificato Let's Encrypt |
| **Revoca cert** | Revoca il certificato e lo rimuove dall'host |
| **Elimina** | Rimuove host e vhost nginx (il certificato viene revocato se presente) |

La colonna **TLS** mostra se il certificato è valido, in scadenza (< 30 giorni) o assente. La colonna **Accesso** mostra il nome della lista di accesso o "Pubblica".

---

#### Liste di Accesso

Le liste di accesso sono policy riutilizzabili che combinano autenticazione HTTP Basic e regole IP allow/deny. Possono essere assegnate a uno o più Proxy Host.

##### Creare una Lista di Accesso

1. Premere **Nuova Lista**.
2. Nel tab **Dettagli**:
   - **Nome**: identificatore della lista.
   - **Satisfy Any**: se attivo, basta soddisfare autenticazione *oppure* regola IP (nginx `satisfy any`); se disattivo, devono essere soddisfatte entrambe.
   - **Passa auth al backend**: se attivo, l'header `Authorization` viene inoltrato al servizio interno.
3. Nel tab **Autorizzazioni**: aggiungere coppie username/password per l'autenticazione HTTP Basic. Alla modifica, lasciare la password vuota per mantenerla invariata.
4. Nel tab **Regole**: aggiungere regole IP.

| Campo | Opzioni | Esempio |
|-------|---------|---------|
| **Azione** | `allow` / `deny` | `allow` |
| **Indirizzo** | IP singolo o CIDR | `192.168.1.0/24` |
| **Ordine** | Numero intero | `1` |

> Se esistono regole IP, nginx aggiunge automaticamente `deny all` in fondo. Mettere prima le regole `allow` specifiche, poi eventuali `deny`.

5. Premere **Salva**.

Una lista può essere eliminata anche se è assegnata a degli host — verrà automaticamente dissociata.

---

#### Certificati SSL/TLS

Il tab **Certificati** mostra tutti i certificati emessi con:
- Domini coperti
- Provider (`Let's Encrypt` o `Custom`)
- Data di emissione e scadenza
- Stato: **Valido** / **In scadenza** (< 30 giorni) / **Scaduto**

Azioni disponibili: **Rinnova** (rilancia certbot) e **Revoca**.

> Il rinnovo automatico è gestito da certbot tramite un hook installato in `/etc/letsencrypt/renewal-hooks/deploy/`. Non è necessario rinnovare manualmente se il dominio è raggiungibile dall'esterno sulla porta 80.

---

#### Come funziona internamente

- nginx viene configurato con file in `/etc/nginx/madmin-revproxy/`.
- Ogni Proxy Host genera un file `madmin-proxy-{id}.conf` in `/etc/nginx/sites-available/` con symlink in `sites-enabled/`.
- Un vhost catch-all (`madmin-acme.conf`) serve le challenge ACME HTTP-01 su porta 80 per tutti i domini, anche prima che il certificato esista.
- Le liste di accesso generano file htpasswd in `/etc/nginx/madmin-revproxy/htpasswd/` e snippet di configurazione in `/etc/nginx/madmin-revproxy/snippets/`.
- Dopo ogni modifica nginx viene ricaricato automaticamente (`systemctl reload nginx`).

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

- **Esporta backup**: scarica un archivio con la configurazione del sistema (utenti, firewall, impostazioni, dati e file dei moduli)
- **Importa backup**: ripristina una configurazione da un archivio precedente, con anteprima di cosa verrà importato. È anche il modo per aggiornare MADMIN: esportare la configurazione, installare la nuova versione e importarla
- **Backup pianificati**: backup automatici giornalieri o settimanali, conservati in locale e caricati su un server remoto **SFTP** o **FTPS**, con retention in giorni
- **Passphrase di cifratura archivi**: se impostata (minimo 12 caratteri) gli archivi vengono cifrati; senza passphrase non si ripristinano, va conservata fuori dalla macchina
- **Chiave del server SFTP**: registrata alla prima connessione; se il server ne presenta una diversa la connessione viene rifiutata

Le password (SMTP, server remoto) e i segreti 2FA sono legati alla chiave dell'installazione: importando un archivio su una nuova installazione vanno reinseriti e il 2FA va riconfigurato.

### Sicurezza

- **2FA obbligatoria globalmente**: se attivo, tutti gli utenti devono configurare il 2FA
- **Durata token**: minuti di validità della sessione (predefinito: 720 = 12h)
- **Porta di gestione**: la porta HTTPS del pannello. Al cambio, MADMIN mostra le regole firewall INPUT che aprono la porta attuale, le copia per la nuova porta prima di spostare il pannello e chiede cosa fare delle vecchie (disattivarle o lasciarle). Richiede anche il permesso `firewall.manage`

### Audit

- **Retention log**: quanti giorni conservare i log di audit (i log più vecchi vengono eliminati automaticamente)

### Syslog esterno

Inoltra l'audit log a un server syslog (RFC 5424) via UDP, TCP o TLS: host, porta, facility, nome applicazione, quali eventi inoltrare (tutti, solo errori) e se includere le letture. Con TLS si può indicare il certificato CA e la verifica del server. **Invia test** manda un messaggio di prova. Modificare la destinazione richiede i permessi `settings.manage` e `logs.view`.

---

## 10. Configurazioni Comuni

Esempi tipici con il firewall del portale. Negli esempi `eth0` è la WAN e `eth1` la LAN.

---

### 10.1 Navigazione Internet della LAN

**Scenario:** i dispositivi della rete `192.168.1.0/24` su `eth1` devono uscire su Internet con l'IP pubblico della macchina.

**Dove:** vista **Standard** → **Nuova regola**

| Campo | Valore |
|-------|--------|
| Interfaccia di ingresso | `eth1` |
| Interfaccia di uscita | `eth0` |
| Sorgente | `192.168.1.0/24` (o vuoto) |
| Azione | Consenti |
| NAT | attivo (si attiva da solo scegliendo la WAN) |
| IP di uscita | IP dell'interfaccia di uscita |

Con l'IP dell'interfaccia il NAT segue automaticamente un eventuale cambio di IP pubblico (MASQUERADE).

---

### 10.2 Port forwarding verso un server interno

**Scenario:** le connessioni sull'IP pubblico alla porta 8080 devono arrivare al server interno `192.168.1.10` sulla porta 80.

**Dove:** vista **Standard** → **Port Forwarding** → **Nuovo port forward**

| Campo | Valore |
|-------|--------|
| Interfaccia di ingresso | `eth0` |
| Protocollo | TCP |
| Porta esterna | `8080` |
| IP interno | `192.168.1.10` |
| Porta interna | `80` |

Il traffico inoltrato viene consentito automaticamente. Attivare **NAT hairpin** se anche i client LAN devono usare l'IP pubblico. Se compare il badge *Bloccato da #n*, una regola *Nega* lo blocca.

---

### 10.3 Uscire con un IP pubblico specifico

**Scenario A:** il server `192.168.1.50` deve uscire su Internet con l'IP secondario `1.2.3.4` invece di quello principale.

1. Aggiungere `1.2.3.4` all'interfaccia `eth0` dalla sezione [Interfacce di Rete](#5-interfacce-di-rete).
2. Vista **Standard** → **Nuova regola**, **sopra** la regola generica di navigazione:

| Campo | Valore |
|-------|--------|
| Interfaccia di ingresso / uscita | `eth1` → `eth0` |
| Sorgente | `192.168.1.50` |
| Azione | Consenti |
| NAT | attivo |
| IP di uscita | `1.2.3.4` |

Ogni connessione esce con il NAT della prima regola che la consente: se la regola generica fosse più in alto, questa riceverebbe il badge *Mai raggiunta*.

**Scenario B:** una subnet deve uscire con un blocco di IP pubblici. Creare un **IP Pool** in **Oggetti** e sceglierlo come *IP di uscita* della regola.

---

### 10.4 Bloccare un IP o una rete

**Traffico che attraversa la macchina** (es. impedire a `192.168.1.66` di uscire): vista **Standard**, regola con sorgente `192.168.1.66`, azione **Nega**, posizionata **sopra** le regole che la consentirebbero. Dopo il salvataggio MADMIN propone di chiudere le connessioni già aperte.

**Traffico verso la macchina stessa** (es. bloccare `1.2.3.4` in ingresso): vista **Avanzata** → Filter → INPUT, regola con sorgente `1.2.3.4` e azione `DROP`, sopra le regole ACCEPT.

---

### 10.5 Aprire un servizio della macchina

**Scenario:** consentire SSH (porta 22) dalla WAN verso la macchina.

**Dove:** vista **Avanzata** → Filter → INPUT

| Campo | Valore |
|-------|--------|
| Protocollo | `tcp` |
| Porta | `22` |
| Interfaccia In | `eth0` |
| Azione | `ACCEPT` |

La regola deve stare **sopra** la regola DROP finale della catena (altrimenti riceve il badge *Mai raggiunta*). Le connessioni già stabilite sono accettate automaticamente: non serve una regola ESTABLISHED. Le porte dei moduli VPN vengono aperte dai moduli stessi.

---

*Documento generato per MADMIN — Sistema di amministrazione modulare per Ubuntu 24.04*
