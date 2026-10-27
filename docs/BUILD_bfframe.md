# bfframe build sheet

Frame for Burke and Fafa. Built and tested at home, then shipped to their house (remote only after that, like mnbframe).
General install steps are in `PI_SETUP.md`; this sheet only has what is specific to bfframe.

## Settings

| Setting | Value |
|---------|-------|
| Hardware | Raspberry Pi 5 (first Pi 5 frame) |
| OS | Raspberry Pi OS (64-bit) |
| Hostname / frame name | `bfframe` |
| User | `pi` |
| Branch | `main` (production) |
| Home LAN IP | `192.168.102.215`, UniFi DHCP reservation on MAC `88:a2:9e:72:c3:7d` (already in place, checked 2026-10-26). Not set on the Pi, so their router hands out an address once it moves |
| Tailscale IP | — (fill in after install) |
| Dashboard | `http://bfframe.whale-ayu.ts.net:8000` |
| Cloud | Koofr, shared account `koofr.obtain355@passmail.net` (same as kframe and mnbframe) |
| Koofr app password | In Matt's password manager. Never in a repo |
| First album | Display name `bfframe` → cloud folder `KFR_bfframe` |

## 1. Flash

Raspberry Pi Imager, Raspberry Pi OS (64-bit). In the settings:
- Hostname `bfframe`, user `pi`
- Enable SSH
- Wi-Fi: **home** network (7Oaks). Setting it here keeps it as its own profile, so adding their network later (step 5) doesn't remove it

## 2. Install

Make a one-time Tailscale auth key (admin → Settings → Keys), then on the Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/watmatt00/wanderwall_frame/main/scripts/setup/install.sh -o /tmp/install.sh && sudo bash /tmp/install.sh --frame-name=bfframe --branch=main --ts-authkey=tskey-auth-XXXX
```

At the prompts: branch `main` (Enter), then the Koofr email and app password. The password is typed, not passed as a flag, so it stays out of shell history.
Follow along with `tail -f ~/install_log.txt` (about 15-20 minutes, several reboots).

## 3. First album

Dashboard → Albums → Add Album → Display Name `bfframe`. That makes `KFR_bfframe` in Koofr.

- Use uppercase `KFR_`. Album ownership and Recover Albums only count `KFR_*` folders (`src/services/frame_registry.py:53`)
- Don't create the folder in Koofr ahead of time. If any `kfr_bfframe` / `KFR_bfframe` already exists, Add Album picks `KFR_bfframe_2` (case-insensitive check, `src/services/source_manager.py:33`). If one does exist, take it over with Backups → Recover Albums instead
- The account is shared, so the album list marks it `shared` and keeps bfframe's folders apart from kframe's and mnbframe's

## 4. Test at home

Run the frame here for a few days before shipping. Being the first Pi 5, check in particular:
- Display engine shows photos and fades between them; videos play
- Indicator lights overlay
- Sync Now, Restart Frame, Reboot Frame from the dashboard
- Tailscale and Funnel (`https://bfframe.whale-ayu.ts.net`); pair the Manager app
- Optional: `bash ~/wanderwall_frame/scripts/setup/install_inspect_key.sh` so Claude can do read-only checks, then add `bfframe` / `bfframe-vpn` hosts to `~/.ssh/config` (claude-config repo)

## 5. Their Wi-Fi, before shipping

```bash
sudo wanderwall-config --wifi-ssid "THEIR_SSID" --wifi-password "THEIR_PASSWORD"
```

This writes the `wanderwall-wifi` NetworkManager profile (priority 10, `scripts/setup/wifi_config.py:41`). The home profile from the Imager stays, so the frame keeps using home Wi-Fi until it can see theirs.
It can't be tested here. Double-check the SSID and password; if they're wrong, someone at their house has to use the setup hotspot (`WanderWall-bfframe`).

`wanderwall-config --wifi-ssid` replaces any earlier `wanderwall-wifi` profile, so if home Wi-Fi was set through the setup hotspot instead of the Imager, this removes it.

## 6. After it moves

- Check it shows up on Tailscale and the dashboard loads over `bfframe.whale-ayu.ts.net`
- Fill in the Tailscale IP above and in the device tables (`CLAUDE.md` here and the global one)
- Consider making a new Koofr app password and entering it under Settings (the current one was pasted in a chat)
- Production frame from here on: no `git pull` / `update_app.sh` without Matt's OK
