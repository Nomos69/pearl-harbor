# Pearl Harbor

Pearl Harbor is a two-player, historically inspired strategy game with a
native Python/Tkinter desktop GUI. Players choose exactly one side—**US** or
**Japan**—and command historically named ships associated with the December 7, 1941
attack. The generated aerial Pearl Harbor battlefield appears beneath the 10×10 grids.
It does not use a browser, HTML, CSS, or JavaScript. An authoritative Python server
keeps both fleets private, validates turns, and exchanges JSON messages with each GUI
over WebSockets.

The main menu separates **Host Operation** from **Join Operation**. The host chooses US
or Japan and creates a lobby immediately; the server returns a random six-character code.
The guest enters that shareable code without choosing a country, and the server always
assigns the country opposing the host. There can never be two US players or two Japan
players.

The GUI uses five distinct realistic top-down ship illustrations for the carrier,
battleship, cruiser, submarine, and destroyer. Pillow scales and rotates the transparent
assets across their grid cells and renders targeting reticles, explosions, and water
splashes rather than text dots or browser assets. It opens on a classic military-RTS
inspired command menu with a tactical Pearl Harbor map, mission briefing, and native
desktop controls. The same red-and-steel command-console design continues through the
radar lobby, fleet deployment, dual battlefield, live intelligence bar, and cinematic
victory or defeat debriefing screens. Native Pillow-rendered US and Japan flags appear
on the country command cards and follow the server-assigned side through every phase.
The lobby radar continuously sweeps, illuminates contacts, and reports whether it is
broadcasting a hosted lobby or searching for one. Waiting and synchronization screens
rotate archive-verified quotations from historical military and political figures every
three seconds. After victory or defeat, each player acknowledges the final report and
returns independently to a clean main menu.

Quotation references: [FDR's Pearl Harbor address](https://www.archives.gov/milestone-documents/joint-address-to-congress-declaration-of-war-against-japan),
[Eisenhower's D-Day order](https://www.archives.gov/milestone-documents/general-eisenhowers-order-of-the-day),
[U.S. Navy famous quotations](https://www.history.navy.mil/browse-by-topic/heritage/famous-navy-quotations.html),
[MacArthur recordings](https://www.archives.gov/research/foreign-policy/voices-of-postwar.html),
and [Churchill in Hansard](https://www.parliament.uk/about/living-heritage/transformingsociety/private-lives/yourcountry/collections/churchillexhibition/churchill-the-orator/human-conflict/conflict2/).

This is not a literal simulation. Historically, the Japanese carrier force launched
aircraft from outside Hawaii and did not fight a symmetric surface battle inside the
harbor. Grid sizes and turns are balanced gameplay values, not real-world scale.

The country-selection screen is a sourced historical dossier covering the
Hawaii Operation, political and military leaders, the 7:55 a.m. first wave, the Japanese
carrier force, and the historical role or fate of every ship represented in the game.
The host chooses US or Japan directly on its dossier card before creating a lobby. A
joining player bypasses country selection because its opposing fleet is assigned by the
server. The five-ship rosters are clearly identified as balanced selections rather than
complete historical orders of battle.

Historical references: [U.S. Naval History and Heritage Command attack overview](https://www.history.navy.mil/research/library/online-reading-room/title-list-alphabetically/p/the-pearl-harbor-attack-7-december-1941.html),
[NHHC Japanese forces](https://www.history.navy.mil/our-collections/photography/wars-and-events/world-war-ii/pearl-harbor-raid/japanese-forces-in-the-pearl-harbor-attack.html),
[National Park Service Hawaii Operation history](https://www.nps.gov/articles/pearlattackww2.htm),
[FDR Presidential Library](https://www.fdrlibrary.org/iw/wwii-facts), and
[Prime Minister's Office of Japan](https://japan.kantei.go.jp/past_cabinet/index.html).

```text
Azure Ubuntu VM: WebSocket server + host GUI process
                                      |
                         TCP 8765 / WebSocket
                                      |
Ubuntu laptop: guest GUI + forwarded display for Azure host
```

Follow these sections in order. Complete each check before moving to the next one.

## 1. Prepare both Ubuntu 24.04 machines

Run on both the Azure VM and laptop:

```bash
sudo apt update
sudo apt install -y python3-venv chrony git
sudo systemctl enable --now chrony
timedatectl status
chronyc tracking
```

Check that `System clock synchronized: yes` appears. The time zones do not have to
match because synchronization and game timestamps use UTC.

Install Tkinter on every machine that runs a GUI. For the Azure-host-player setup,
install Tkinter and X11 authorization support on the VM too:

```bash
sudo apt install -y python3-tk xauth
python3 -c "import tkinter; print('Tkinter', tkinter.TkVersion)"
```

## 2. Install the project on both machines

Copy or clone the project, enter its directory, and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Check the WebSocket library:

```bash
python -c "import websockets; print(websockets.__version__)"
```

It should print `17.0`.

## 3. Test the native GUI locally

On the laptop, start the server in terminal 1:

```bash
cd "/path/to/Client-Server Application"
source .venv/bin/activate
python server.py
```

Start the first desktop window in terminal 2:

```bash
cd "/path/to/Client-Server Application"
source .venv/bin/activate
python gui_client.py
```

Start the second desktop window in terminal 3:

```bash
cd "/path/to/Client-Server Application"
source .venv/bin/activate
python gui_client.py
```

Two native Pearl Harbor windows should appear. In the first window choose **Host
Operation**, select US or Japan, and create the lobby. Copy the generated lobby code. In
the second window choose **Join Operation** and enter that code; no country selection is
requested. The server automatically assigns the opposing country. Each side receives its
own historically named fleet. Place five ships, then click
**Lock deployment**. The side that connected first attacks first by
clicking an unknown cell on the enemy grid. A hit earns another attack; the turn passes
to the opponent only after a miss.

## 4. Open the Azure network path

In Azure Portal open the VM, then **Networking > Network settings > Create port rule
> Inbound port rule**. Use:

- Source: the laptop's public IP address
- Source port ranges: `*`
- Destination: `Any`
- Service: `Custom`
- Destination port: `8765`
- Protocol: `TCP`
- Action: `Allow`
- Priority: an unused value such as `310`
- Name: `Allow-Pearl-Harbor-WebSocket`

If UFW is active on the VM, allow the same laptop address:

```bash
sudo ufw status
sudo ufw allow from LAPTOP_PUBLIC_IP to any port 8765 proto tcp
```

Replace `LAPTOP_PUBLIC_IP` with the laptop's numeric public IP.

## 5. Start the server on Azure

SSH into the Azure VM and run:

```bash
cd "/path/to/Client-Server Application"
source .venv/bin/activate
python server.py
```

In another SSH terminal, verify it:

```bash
ss -ltnp | grep 8765
curl http://127.0.0.1:8765/healthz
```

The first command should show `0.0.0.0:8765`; the second should print `OK`.

## 6. Run the Azure host player and laptop guest

The Azure VM is headless, so open a second laptop terminal with X11 forwarding. The
process runs on Azure while its native Tkinter window is displayed on the laptop:

```bash
ssh -X -i ~/.ssh/pearl-harbor-key.pem azureuser@AZURE_PUBLIC_IP
cd ~/pearl-harbor
source .venv/bin/activate
python gui_client.py \
  --uri ws://127.0.0.1:8765/ws
```

In that window choose **Host Operation**, select the host country, create the lobby, and
copy the displayed six-character code.

On the Ubuntu laptop, open its own local GUI:

```bash
cd "$HOME/Special Topics in Networking/Client-Server Application"
source .venv/bin/activate
python gui_client.py \
  --uri ws://AZURE_PUBLIC_IP:8765/ws
```

Choose **Join Operation**, enter the lobby code, and connect. The laptop guest is assigned
the country opposing the Azure host.

If the GUI cannot connect, check in this order: Azure server process, `ss`, UFW,
Azure NSG source address, and the VM public IP.

## 7. Install the Azure server as a service

After the manual Azure test works:

```bash
sudo useradd --system --home /opt/battleship --shell /usr/sbin/nologin battleship
sudo mkdir -p /opt/battleship
sudo cp game.py server.py requirements.txt /opt/battleship/
sudo python3 -m venv /opt/battleship/.venv
sudo /opt/battleship/.venv/bin/pip install -r /opt/battleship/requirements.txt
sudo chown -R battleship:battleship /opt/battleship
sudo cp deploy/battleship.service /etc/systemd/system/
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now battleship
sudo systemctl status battleship --no-pager
```

View server logs with:

```bash
sudo journalctl -u battleship -f
```

## 8. Clock synchronization

There are two synchronization layers:

1. `chrony` synchronizes both Ubuntu system clocks using NTP.
2. When the GUI connects, it exchanges four timestamps with the server and displays
   the estimated server clock offset and WebSocket round-trip delay.

The server remains authoritative for every turn, preventing client clock differences
or network delay from granting extra moves.

## 9. Security and optional TLS

Plain `ws://` traffic is not encrypted. Use it only for a controlled class exercise
with the Azure NSG limited to the players' public IP addresses. Lobby hosting intentionally
has no host key, so any client that can reach port `8765` can claim the server's single
active lobby. For internet-wide access, add an authentication layer and use a DNS name
with TLS:

```bash
python server.py --certfile /path/to/fullchain.pem --keyfile /path/to/privkey.pem
python gui_client.py --uri wss://your-domain.example:8765/ws
```

## Automated tests

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest -q
```

`client.py` is retained as an optional terminal protocol-debugging tool. Normal
players should launch `gui_client.py`.
