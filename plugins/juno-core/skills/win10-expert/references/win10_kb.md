# Windows 10 Kunskapsbas (`win10_kb.md`)

> Hybrid kunskapsbas: kombinerar snabba lokala felsökningskartor + `ms-settings:`-genvägar med live-uppslag mot `learn.microsoft.com` när nya felkoder dyker upp.

---

## 1. Symptom -> Troliga orsaker -> Kontroll

| Symptom | Troliga orsaker | Kör i `win10_doctor.py` |
| :--- | :--- | :--- |
| **Datorn känns seg / fläkten går på högvarv** | Autostart-program, kraschande bakgrundstjänst, väntande omstart, full temp-mapp eller gammal hårdvara med hög I/O | `diagnose --section system startup disk events` |
| **Windows Update fastnar eller ger fel** | `wuauserv` / `bits` stoppad, skadade systemfiler, för lite diskutrymme | `diagnose --section services disk events` + ev. `sfc /verifyonly` |
| **Ljud, Bluetooth eller USB strular** | Felkod på PnP-drivrutin (`ConfigManagerErrorCode != 0`), stoppad `Audiosrv`, strömsparläge | `diagnose --section drivers services` |
| **Nätverk / Wi-Fi tappar kontakt** | DNS-strul, `Dhcp`/`Dnscache`-tjänst, trasig nätverksdrivrutin | `diagnose --section network drivers services` |
| **Orolig för virus / konstigt beteende** | Avstängt Defender-skydd, okända autostartposter, skumma Event-fel | `diagnose --section security startup events` |

---

## 2. Snabbgenvägar till Windows 10-inställningar (`ms-settings:`)

När en ändring kräver flera menyer, öppna rätt inställningssida direkt med `win10_doctor.py open-setting <uri>`:

* `ms-settings:windowsupdate` — Windows Update & uppdateringshistorik
* `ms-settings:startupapps` — Autostart-appar (enkelt stänga av tunga program)
* `ms-settings:storagesense` — Lagringsutrymme & temporära filer
* `ms-settings:sound` — Ljudenheter, mikrofon & volymmixer
* `ms-settings:bluetooth` — Bluetooth & anslutna enheter
* `ms-settings:network-status` — Nätverksstatus & återställning
* `ms-settings:windowsdefender` — Windows-säkerhet & virusskydd
* `ms-settings:privacy` — Sekretess & bakgrundsappar
* `ms-settings:troubleshoot` — Windows inbyggda felsökare

---

## 3. Flerstegs-inställningar (vanliga fällor i Windows 10)

* **Få en äldre burk märkbart piggare (3 steg):**
  1. Stäng av tunga autostart-appar (`ms-settings:startupapps`).
  2. Aktivera Storage Sense / rensa temp (`ms-settings:storagesense`).
  3. Kontrollera energischema + väntande omstart (`diagnose --section system`).
* **Åtgärda Windows Update som hängt sig (efter backup + ditt OK):**
  1. Kontrollera `wuauserv` & `bits`.
  2. Kör `DISM /Online /Cleanup-Image /CheckHealth` (läsning) före ev. `RestoreHealth` + `sfc /scannow` (kräver Admin/UAC + ditt OK).

---

## 4. Hur kunskapsbasen hålls levande
* **Lokalt:** Beprövade felsökningsmönster och dina egna maskinnoteringar sparas här i `win10_kb.md`.
* **Online (live):** För nya Windows-uppdateringar, specifika felkoder (`0x8007...`) eller drivrutiner söker `win10-expert` automatiskt på `site:learn.microsoft.com` och fyller på nya bra lösningar här.
