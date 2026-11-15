# SwarmBox architecture

This is the current design of SwarmBox 2.0, written from the code. The first public version is `2.0.0`. Facts that were
measured say how; anything not run on a real host is listed in "Not done, and open questions". The older process records
(decision log, build plan, overnight report) are in [history/](history/README.md); they are not documentation.

Contents: 1 Purpose, 2 The box model, 3 Directories and paths, 4 Commands, 5 The shared session, 6 Startup of the box,
7 Web terminal and remote access, 8 Tools and shims, 9 Configuration, 10 Environment variables, 11 Nested Podman,
12 Security model, 13 Image and updates, 14 Repository layout, 15 Decisions, 16 Not done and open questions.

## 1. Purpose

SwarmBox is a persistent sandbox for running AI coding agents (Claude Code, Gemini CLI, OpenCode) in auto-approve mode
on your own machine. It is one long-lived, rootless Podman container, the **box**, with one folder of your machine, the
**workspace**, mounted as its home. You enter it from any terminal tab or from a browser, and every entry lands in the same
tmux session. The aim is that a mistake of the agent is limited to one folder, not that untrusted code becomes safe (section 12).

Goals: one command to start (`swarmbox`); one shared session for every client; a small neutral image with tools installed
when first used; everything that must survive in one folder; no telemetry; remote access without putting credentials in the box.

Non-goals: a virtual machine boundary (see [microvm.md](microvm.md)); Docker or rootful Podman; Windows without WSL2;
a throwaway-container mode; tools per project.

Supported hosts: Linux, macOS through a Podman machine (not verified), and WSL2 with the workspace on the Linux filesystem.
Podman 4.3 or newer.

## 2. The box model

```
 HOST (your machine)                                             IMAGE  ghcr.io/feroult/swarmbox:X.Y.Z
 +-------------------------------------------+                   neutral: shell environment, tmux, ttyd,
 | script `swarmbox`  (a file on your PATH)  |   podman run/     Podman, Node, swarmbox-tool, tool manifests
 | support files host:~/.local/share/        |   exec            (no agent inside)
 |              swarmbox/host/               | ------------------------+
 | config       host:~/.config/swarmbox/     |                         | the box is created from it
 | Cloudflare connector (a container, host)  |                         v
 +----------+--------------------------------+          BOX  one container named `swarmbox`
            |  127.0.0.1:7681                           +----------------------------------------------+
            +------------------------------------------>| serve  (the box's main process, PID 1)       |
                                                        |  +- tmux server, session `main`  <- every tab |
 WORKSPACE  host:~/swarmbox   ===== mounted as =======> |  +- ttyd -> tmux   (the web terminal)         |
 (projects, .ssh, .claude, tools, in-box config)        |  +- nested Podman service                     |
                  /home/agent  (the home)               |  +- tools, reached through shims, installed   |
                                                        |     into the workspace on first use           |
                                                        +----------------------------------------------+
 browser ---> https://swarmbox.example.com ---> Cloudflare Access ---> connector ---> 127.0.0.1:7681
```

- **One persistent box per workspace.** Entering never creates a second box. A second box is a different name
  (`SWARMBOX_NAME`) with its own workspace and web port.
- **Neutral image, tools on demand.** The image holds the shell environment only; agents and CLIs are installed into the workspace
  on first use (section 8).
- **The workspace is the home and the only thing that must survive.** The box can be deleted and recreated (`swarmbox reset`);
  projects, logins, the SSH key and installed tools are in the workspace.
- **A thin host half.** One POSIX `sh` script, `swarmbox`, on your `PATH` drives Podman: no shell function, no startup file. Cloudflare credentials and the connector
  stay on the host, outside the box.
- **One configuration surface**, applied when the box is created and compared on every entry (section 9).

Glossary: the **script** is the `swarmbox` command (the file `container/host/swarmbox-host` in the repository), written to your `PATH` by an installer; the
**support files** are `VERSION`, `DEFAULTS`, `cloudflare-setup.py` and `tool-ports`, which one file cannot hold and the image carries; a **tool** is a program installed on demand; an **agent** is a tool with `KIND=agent`; a **shim** is a link on `PATH` named
after a command of a tool; a **manifest** is a tool's `tool.conf`; a **creation setting** is fixed when the box is created and
changes with `swarmbox reset`, a **runtime** setting changes in the running box.

## 3. Directories and path notation

In documents: `host:~/...` is a path on your machine; `<workspace>/...` is inside the workspace folder (inside the box the workspace is
`/home/agent`, so `<workspace>/.config/swarmbox/` is `~/.config/swarmbox/` there); `box:/...` is the container's own filesystem,
which a `reset` discards.

```
host:~/swarmbox/                       # the workspace = /home/agent in the box (default; `swarmbox config set WORKSPACE DIR`)
├── my-project/                        # your projects
├── .ssh/                              # the box's SSH key (id_ed25519, id_ed25519.pub)
├── .claude/, .claude.json             # Claude Code: login, settings, history
├── .config/swarmbox/                  # you edit: web-terminal.conf, user-level tool manifests, mcp/<name>/config.json
├── .local/share/swarmbox/             # installed: tools/<name>/..., shims/, index
├── .local/state/swarmbox/             # logs (serve.log, podman-service.log, web-terminal.log), health, podman.sock
└── .local/share/containers/           # empty here: the nested Podman storage is a volume

host:~/.config/swarmbox/config                 # host configuration (second box: <name>/config); cloudflare.json
host:~/.local/bin/swarmbox                     # the script ($SWARMBOX_BIN_DIR to change the folder); mode 755
host:~/.local/share/swarmbox/host/             # the support files, extracted from the image
host:~/.local/state/swarmbox/                  # lock folders, `notices`, and <name>.sock-dir when the workspace path is long
box:/tmp/swarmbox/                             # tmpfs, empty at every start: ready marker, rendered web page, locks, exit.<id>
volume <name>-containers                       # nested Podman storage, mounted at <workspace>/.local/share/containers
```

The layout follows XDG and every script reads it from `container/scripts/dirs.sh` (honours `XDG_CONFIG_HOME`, `XDG_DATA_HOME`,
`XDG_STATE_HOME`). Rule per file: must it survive a reset, and must the host reach it? The config you edit is in `.config`, what
was installed in `.local/share`, logs and the one socket the host needs in `.local/state`, what is regenerated at every start in
`box:/tmp/swarmbox`. The host config and the in-workspace config share names because both follow XDG, but are different places:
the host one is read before the box exists.

What a reset or an image update keeps: the workspace (yes), the volume `<name>-containers` (yes), the container's own filesystem
(no: `apt` installs, files in `/usr`, `/etc`, `/opt`, running processes, tmux sessions).

Workspace rules. The folder is created on first start. A workspace that is not writable exits 4. A workspace under `/mnt/<letter>/`
on WSL is refused (exit 4): permissions and `keep-id` do not behave on a Windows drive. On macOS a folder not shared with the Podman
machine is exit 4 (not verified). A workspace already used by another box (label `swarmbox.workspace`) is exit 5. Changing
`WORKSPACE` in the config moves nothing: the box keeps its mount and every entry warns until `reset`.

The host reaches the nested Podman through a unix socket, `podman -c <name>` (Linux and WSL only; unix sockets do not cross the macOS VM).
A socket path holds at most 107 characters. When `<workspace>/.local/state/swarmbox/podman.sock` is longer than 100 bytes the script
registers the connection through a short symlink `host:~/.local/state/swarmbox/<name>.sock-dir`; if that is still too long `up` exits 4.
Measured with a stand-in server, Podman 4.3.1.

## 4. Commands

Every `swarmbox <word>` is handled by the script or forwarded into the box. Its own words win and are reserved: `stop`, `reset`, `up`, `url`,
`update`, `config`, `env`, `remote`, `fingerprint`, `version`, `help`, `--help`, `-h` (and `create-flags`, `connection` and `setup`, which are internal). `pubkey`, `tool`, `bus` and `tabs` go
to the box as they are; `attach` and any other first word run `up` and then `podman exec` into the box (`-t` only when stdin and stdout are
terminals; `TERM` and `COLORTERM` are passed). A command of the box that has a reserved name runs as `swarmbox attach <name>` (so a box program called `bus`, `tabs`, `tool` or `pubkey` does too).

| Command | What it does |
|---|---|
| `swarmbox` | create and start the box if needed, then open a new window of tmux session `main` in it |
| `swarmbox <command> [args]` | run a command in the box in a new tmux window, return with its exit status; the aliases and `PATH` of an interactive shell apply |
| `swarmbox --plain [command]` | the same without tmux: plain bash, or the command directly |
| `up`, `stop`, `reset` | start without a shell; stop (nothing deleted); remove and recreate the box and wait until ready (workspace and volume kept, sessions end) |
| `url` | the web terminal address, and the public one when this box was set up for remote access |
| `update [--to TAG]` | pull a newer image, record it as `IMAGE`, refresh the support files and the script itself (never by an older one), tell you to `reset` |
| `config get\|set\|list` | the host configuration (section 9) |
| `env add\|rm NAME`, `env list` | variables of yours to pass into the box (section 10) |
| `pubkey` | the box's git SSH public key |
| `tool list\|install\|update\|use\|remove\|doctor\|new\|validate` | tools inside the box (section 8) |
| `bus pub\|sub\|topics\|watch\|ping\|restart` | the message bus of the box (section 6); `swarmbox-bus --help` in the box |
| `tabs list\|active\|screen\|send` | the tmux tabs of the box, a capability of the host (section 6); `swarmbox-tabs --help` in the box |
| `remote setup\|status\|off\|token` | remote access through Cloudflare (`--dry-run` shows changes) |
| `version`, `fingerprint`, `help` | script version; creation fingerprint (`--explain` lists differences); the command list |

Inside the box: `claude`, `gemini`, ... (shims, auto-approve by default for agents), `yolo` (the default agent in auto-approve mode),
`swarmbox-web restart`, `swarmbox-tool`, `swarmbox-pubkey`, `swarmbox-bus`, `swarmbox-tabs` (and `swarmbox-sysop` and `swarmbox-voice` once those tools are installed). There is no `swarmbox uninstall`; the manual steps are in [uninstall.md](uninstall.md).

**Exit codes of the script.** 0 ok; 1 failure of Podman or of a file operation; 2 usage or an invalid value; 3 a prerequisite
(Podman missing or older than 4.3, no `/dev/net/tun`, image cannot be pulled, no usable support files or `python3` for `remote`);
4 workspace problem; 5 conflict (another box on the workspace, or a container with the box's name that SwarmBox did not make:
it is never adopted or removed); 6 not ready after 60 s, or the box exited while waiting; 7 the box could not be created.
Standard output carries data, messages go to standard error.

**Install.** Two ways, one result: a file `${SWARMBOX_BIN_DIR:-$HOME/.local/bin}/swarmbox` (mode 755, written through a temporary file and a rename), the support
files in `~/.local/share/swarmbox/host/`, and the image and tools in the host config (`IMAGE`, `WITH`, only the keys that are not set yet).
Next to the script `setup` writes `sx`, a two-line script that runs the `swarmbox` beside it (a script, not a link: the script names itself by `$0` and `update` renames
a new copy over that name). It is written only when nothing else answers to `sx` (no other file of that name in the folder, no `sx` on the `PATH`), never overwrites one, and `SWARMBOX_NO_SX=1` skips it.

```
podman run --rm <image> install [--with TOOLS] | sh        # from an image; run it without `| sh` to read it first
sh install.sh [--version X.Y.Z] [--image REF] [--with TOOLS]  # from a release: downloads swarmbox, checks swarmbox.sha256
```

**The pull.** `pull_image` (used by `up`, `update` and `setup`) draws a progress line when standard error is a terminal, and is quiet (`-q`) otherwise. The line is one `ui_pull` loop
in the script: `podman pull` runs in the background with its own output in a file (the last line is the reason when it fails), and every 0.25 s the loop draws four colored blocks (`pull`, a 16-cell bar with the
percentage, MB done of the total, MB/s and seconds; narrow terminals drop the right-hand blocks). The bytes are the size of `container_images_storage*` in the temporary folder that `podman info` reports as
`ImageCopyTmpDir` (measured on Podman 5.4: it grows to about the compressed size of the image while the layers arrive); the total is the sum of the layer sizes of the manifest for this machine's architecture,
read from `ghcr.io` with `curl` in the background (any other registry, or any failure, gives a bar that sweeps with no percentage). The percentage never goes back and stops at 99 until Podman exits; when it is
95 or more and no bytes arrive the label is `unpack`. The line is words and a bar, in the violet and gray of the box (24-bit with `COLORTERM`, else 256), off with `NO_COLOR`; it draws no glyph that needs a Nerd Font and no background;
without a UTF-8 locale the bar is ASCII; `SWARMBOX_PROGRESS=plain` leaves Podman's own bars. [verified: tests/test_pull_ui.py with a fake Podman and curl, and a real
pull of the 2.0.4 image: 785 MB, 99% at 749 MB, 24 s; Podman 5.4.2] Not checked: Podman 4.3 to 5.3 (the folder name is the same in the containers/image library for years), macOS, a registry other than ghcr.io.

`install` runs in a container and prints a small POSIX `sh` installer that carries the script in a quoted here-doc; it writes nothing itself. The
image it records is `--image`, else the name Podman recorded for the container (`/run/.containerenv`, so a local build is found under its own
name), else the default repository at the image's version. The installer writes the script and runs `swarmbox setup --image REF [--with TOOLS]`, which both ways share:
it checks that Podman exists and is 4.3 or newer, extracts the support files from the image (`podman run --rm <image> host-helper` writes a tar archive,
checked for member names, unpacked into a temporary folder, and renamed into place), records `IMAGE` and `WITH` the way `config seed` does
(a key that is already set is never overwritten; a different value is reported once), prints the `PATH` advice when the folder is not in `PATH`,
and prints the next command. It never edits a startup file and is idempotent. An older release put a `swarmbox` function between
`# >>> swarmbox` markers in `~/.bashrc`, `~/.zshrc` or `~/.config/fish/config.fish`; the installer only looks for that marker and prints one warning
to delete the block, because a shell function wins over a script on the `PATH`. The script carries its own version (`SCRIPT_VERSION`, equal to
`container/host/VERSION`); when the support files report another version the script prints one short line, once, and `swarmbox update` makes them agree.

**What `up` does**, in order, under a lock (`host:~/.local/state/swarmbox/up-<name>.lock`, an atomic `mkdir`, stale locks reaped,
removed on every exit path):
1. Check Podman (4.3 or newer), the configuration, the workspace, `/dev/net/tun`.
2. Find the box with one `podman container inspect` and an exact name match (Podman also resolves ID prefixes). Read its labels.
3. Running: warn about differences (below) and finish; at most two Podman calls. Stopped: `podman start` and wait. Missing: pull the image
   if absent, resolve `INIT=auto`, build the flags with `create-flags`, `podman run -d --cidfile`, wait. A failed `run` removes only the
   container whose ID is in the cidfile and prints the last lines of Podman's error (exit 7).
4. Wait for readiness: poll `box:/tmp/swarmbox/ready` every second for 60 times, and the container state; an exited container stops
   the wait at once with `podman logs` lines (exit 6).
5. Register the host connection (Linux and WSL).
6. If `WEB=1` and a tunnel token resolves, make sure the Cloudflare connector container is up (section 7).

`reset` does the same checks first, then `podman rm -f <name>`, then `up`. A failed check leaves the old box. `stop` takes no lock,
and exits 0 when there is no box.

**Labels and the fingerprint.** The box is created with the labels `swarmbox.managed=2`, `swarmbox.image`, `swarmbox.workspace`, `swarmbox.ports`,
`swarmbox.env-hash` and `swarmbox.fingerprint`, which are the only state the host keeps about it. The fingerprint is a SHA-256 over the sorted
`KEY=value` lines of the creation settings (`AGENT`, `BROWSER_URL`, `ENV_KEYS` names, `HOSTNAME`, `HOST_ACCESS`, `IMAGE`, `INIT`, `NAME`, `PORTS` with the
tools' ports, `TZ` resolved, `WEB`, `WEB_PORT`, `WITH`, `WORKSPACE`, `YOLO`) plus the hash of the passed variables. On every entry `up`
recomputes it and, when it differs, prints one line per difference it can name and continues: it only warns, because `reset` ends sessions
and must be your choice. It also warns when the box's image is not the one the config asks for or the local image was replaced since.

## 5. The shared session

- `serve` creates tmux session `main` with one idle window named `idle`, so the session exists before the first tab.
- Entering (`swarmbox-attach`, run through `podman exec`) makes a session of its own for the tab, named `swarmbox-tab-*`, with one window, and **links that
  window into `main`**, so the browser lists it as a tab. (Not a grouped session: a group shares the window list of every tab, so when the window
  of a tab ended its client was moved to the window of another tab instead of ending.) `exit` in a tab ends its window, its session (which has no
  window left) and its client: the user is back at the host shell. Closing the tab only detaches: its session ends (`destroy-unattached`), the window
  stays in `main` until its shell exits. The window goes to the place its host tab had: the host script passes `SWARMBOX_TAB`, the `tty` of the terminal (the
  same for as long as the tab lives, in any terminal or over ssh; only with a terminal on both ends), the window keeps it in the window option `@sb_tab`, and the
  server keeps the keys in the order they first appeared in the global option `@sb_order` (the newest 64; the key is cleaned to `A-Za-z0-9._/-`, at most 80
  characters). The window is linked before the first window of `main` whose tab comes later in that order, else at the end, and the target is written
  `=main:@id`: a bare window id is looked up in the first session that has the window, which is the session of the tab that owns it, not `main`. Windows with no
  key (opened from the browser) are not in the order: nothing records on which side of a returning tab they were. When the only other window is the
  untouched idle one (named `idle`, one pane, a shell), it is closed. A host tab has no tmux status bar. The browser (`swarmbox-attach --web`, what ttyd runs) attaches to `main` itself and keeps the bar, so it lists every window, the ones opened from host tabs too.
- Closing every tab or the browser stops nothing; `swarmbox stop` does.
- `attach` waits for the readiness marker (60 s, then exit 6 and a message naming `podman logs`).
- **`swarmbox <command>`** with a terminal: the command runs in a new window through `bash -ic` (so the agent aliases and `PATH` apply) as a
  background job that writes its status to `box:/tmp/swarmbox/exit.<id>` and signals `tmux wait-for`; the call returns that status (a signal
  gives 128+signal; a lost status gives 1). Arguments are quoted with `printf %q`, so spaces, quotes and `$` arrive unchanged. The idle
  window is not closed on this path, or the session would end with the last window. Without a terminal on stdin and stdout (`swarmbox pubkey > file`),
  or with `--plain`, the command runs directly, through `bash -c` with the shell fragment sourced, not an interactive shell, so standard error stays clean.
  Measured with a spike and real tmux 3.3a: exit codes, 17 awkward arguments byte for byte.
- A command named like a host word cannot be run this way: use `swarmbox bash -c '<command>'`.
- tmux config: `container/config/tmux.conf` (prefix `Ctrl+A`, mouse, history, true colour, and `Ctrl+A` then `S` to show or hide the panel of the `sysop` tool); your `~/.tmux.conf` is read after it.

## 6. Startup of the box

`serve` is the container's main process (`CMD ["serve"]` of `swarmbox-entrypoint`, source `container/entrypoint.sh`). The box lives as long as it does.
**F** = fatal (print the reason, exit 1; `podman logs` shows it), **W** = warn and continue (a line in `serve.log` and in `health`, counted in the ready marker).

| # | Step | On failure |
|---|---|---|
| 0 | delete `ready` and `exit.*` in `box:/tmp/swarmbox` (also empty because it is a `--tmpfs`) | |
| 1 | the workspace is a directory the agent user can write in | F |
| 2 | `/dev/net/tun` exists | F |
| 3 | create the XDG folders and `box:/tmp/swarmbox`; clear `health` | F |
| 5 | ensure the SSH key (`swarmbox-pubkey --ensure`) | W |
| 6 | `swarmbox-tool link --user` (shims and index of the user level) | W |
| 6b | start and supervise the bus broker (`swarmbox-bus serve`), wait up to 2 s for it to answer | W |
| 7 | generate the MCP file (`swarmbox-mcp`), then run `prepare.sh` of every tool that is installed or in `WITH` | W per tool |
| 8 | start the nested Podman service on `<state>/podman.sock` and check that it answers (10 s) | W |
| 9 | start tmux with session `main` and the idle window | W |
| 10 | start and supervise ttyd when `WEB=1` | W |
| 11 | write the ready marker: `ok` or `warnings=<n>` | W |
| 12 | in the background, install the tools of `WITH`, one after another, output to `serve.log` | W per tool |

Tools of `WITH` install after the marker, so a slow download never blocks the door. `serve` handles SIGTERM and SIGINT (it sleeps in `wait`
on a background `sleep infinity`), stops its children and exits, so `podman stop` is prompt (0.14 s measured, with and without `--init`).
One supervisor function, `supervise_one`, serves ttyd and the bus broker. It restarts the child with a backoff of 1, 2, 4 ... 30 s; after 5 exits within 60 s it records a health line and stays idle, so that
`swarmbox-web restart` (or `swarmbox-bus restart`) can still restart it by hand; the box does not stop when ttyd or the bus does. A broker that exits 8 (another one holds the lock) is not restarted. The box is created without `--restart`: after a host
reboot it is stopped and the next `swarmbox` starts it (the connector, by contrast, is created with `--restart=always`).
The entry banner shows the health lines. The test-only switches are `SWARMBOX_TEST_*` variables; they are not settings.

### The bus

`swarmbox-bus` (source `container/scripts/swarmbox-bus.py`, one file, standard library only) is the broker and its command line. Rationale and the
spikes behind it are in [plugins-design.md](plugins-design.md). Nothing of the box depends on it; step 6b starts it and a failure is only a warning. The bus is plain publish
and subscribe: it knows nothing about tmux, tabs or what a message means, keeps no state and answers no question about the box (the tabs are a separate command, below).

- **Where.** A unix socket `box:/tmp/swarmbox/bus.sock` (`SB_BUS_SOCK` in `dirs.sh`; `SB_BUS_SOCKET` overrides it for the client and the broker), mode 0600, and the broker refuses
  any uid that is not its own or root (`SO_PEERCRED`). One broker per socket, by `flock` on `bus.sock.lock`; a socket left by a crashed broker is removed by the next one.
  Log `<state>/bus.log`; supervisor pid `box:/tmp/swarmbox/bus-supervisor.pid`. From the host: `swarmbox bus ...` (forwarded like `pubkey` and `tool`).
- **Commands.** `pub [--source S] [--allow-none] [--] TOPIC [MESSAGE|-]` (a big body goes by stdin: one argv string is capped at 128 KiB; a message that starts with `-` goes after `--`; it prints `{"id","receivers"}`),
  `sub [--group NAME] [--raw] TOPIC` (`--raw`: one line per body, plain one-line text as it is, anything else as JSON), `topics` (the topics that have subscribers, as JSON: `topic`, `subscribers`, `groups` with the members of each),
  `watch` (every message with its topic, receivers and result), `ping`, `restart`, `serve`. Exit codes: 0 ok, 1 error, 2 usage, 3 nobody received the message, 4 broker not running, 5 too large,
  6 bad topic, group or request, 7 busy, 8 already running.
- **Topics are free names**: 1 to 64 characters of `A-Za-z0-9_.:-`, starting with a letter or a digit; the bus has no list of topics and no reserved name. Plugins take the name from their settings (`voice.topic`, `sysop.topic`, both `goal` by default).
- **Delivery.** A message goes to every subscriber of its topic that is listening at that moment (broadcast), and subscribers that gave the same `--group` share the work: the group gets the message once, to one member, round robin.
  Nothing is buffered and nothing is acknowledged; the one loss window is a message written to a subscriber that dies before it reads it. A group member that is alive but not reading (an earlier message unread) is skipped, not fed; when every
  member of a group is like that, the group's share fails after a 0.2 s wait and the reply is `busy` (exit 7), still saying how many others received it. A subscriber without a group that is over 4 MiB behind is skipped. NaN and Infinity are not JSON: the CLI sends them as text and the broker refuses them.
- **`pub` counts the receivers**: the subscribers without a group that took the message, plus one for each group that took it. With none it fails with 3 (`no_subscriber`), unless `--allow-none` accepts it (receivers 0).
- **Protocol.** One JSON line per request; `pub`, `topics`, `ping` get one reply line `{"ok":true,...}` (`pub`: `id`, `delivered` = the receivers) or `{"ok":false,"err":CODE,"msg":TEXT}`; `sub` and `watch` get
  `{"ok":true,"subscribed":T,"group":G}` and then one line per event. A line is at most 1 MiB. The envelope `{v,id,topic,source,peer,time,body}`: the broker sets `id`, `time` and `peer`;
  `source` is a label the sender declares, for display and never for authorization. The full text is the docstring of the file.
- **Restart.** While the broker restarts (1 to 30 s) a `pub` fails with 3 and nothing is replayed; a resident subscriber must reconnect with a backoff.

### The tabs

`swarmbox-tabs` (source `container/scripts/swarmbox-tabs.py`, in the image as `/usr/local/bin/swarmbox-tabs`; from the host `swarmbox tabs ...`) is a **capability of the host**, used directly and never through a bus topic. It has no daemon:
a call reads or acts on tmux and ends, and it imports nothing from any plugin. The file is a command line and a library at once; the full text is its docstring.

- **Commands.** `list` (JSON list of the tabs), `active`, `screen TAB [--lines N]`, `send TAB (--run TEXT | --input TEXT) [--queue] [--slash]`; `-` as TEXT reads stdin (long or multi-line text). Everything is JSON on stdout; a failure is
  `{"err":CODE,"msg":TEXT}` on stdout too, with an exit code: 0 ok; 1 refused or failed (`no_such_tab`, `ambiguous_tab`, `dialog_open`, `busy_tab`, `slash_refused`, `not_submitted`, `tmux_error`, `lock_error`); 2 usage or a text that cannot be typed (`usage`, `bad_body`);
  4 tmux is not there (`no_tmux`, `no_session`); 5 `timeout`.
- **Environment.** `SB_TABS_SESSION` (default `main`), `SB_TABS_SOCKET` (adds `-L name`, for tests), `SB_TABS_BIN` (the tmux program), `SB_RUN_DIR` (locks); `TMUX_TMPDIR` passes through and `TMUX` is removed. Every tmux call has a 5 s timeout.
- **The lock.** A send holds an `flock` on `<run folder>/tabs/<window id>.lock` while it types, so two sends to one tab never interleave, from any processes (the kernel drops the lock however the process dies); the second waits up to 30 s, then fails with `timeout` and types nothing. Reads take no lock.
- **For a plugin**, run the command rather than import the file: the command is the contract (JSON, exit codes, lock, timeouts) and costs one Python start-up (about 15 ms); the library (`Tabs`, with `list_tabs()`, `active()`, `screen()`, `send()`, errors as `TabsError`) exists for tests and for the command itself.
- *Tabs.* A tab is a window of `main`. The address is the window id (`@3`); `index:name`, the index and the name are accepted too, and a name used twice is `ambiguous_tab` with the candidates. Every tmux call targets
  the pane id. Panes with the option `@swarmbox_sysop_panel`, or with `SWARMBOX_SYSOP_PANEL=1` in their start command (a pane exists for an instant before its option is set), are never listed or targeted. `active` is the window of the non-control client with the latest activity, else the current window of `main`.
- *Screen.* `capture-pane -p -J -e`, turned into the plain text of the pane plus the style of each character, then the last `lines` lines, then the secrets filter (on the plain text, whole lines, whatever the colours), then the text written with `[sel]` (reverse video), `[bg]` (background colour)
  and `[err]` (red) spans and each line cut to 1000 characters (so no secret is cut in half and no colour hides one). Text of the pane that looks like a marker (`[sel]`, `[/err]`, `[REDACTED]`) gets one more `[` (`[[sel]`), so program output cannot forge one. A full-screen program (alternate screen) has no scrollback, so `lines` is ignored for it (`"lines": null` in the answer).
  The secrets filter is the one of the box, tested in `tests/test_tabs.py` and `tests/test_tabs_redact_dos.py`.
- *Typing.* `--run` types the text literally and presses Enter; `--input` types text with keys in braces (`{Esc}`, `{Enter}`, `{C-c}`, `{Up}`, ... any other `{word}` is text, `{{` is a brace). The text goes in pieces of 1024 characters (a `;` at the end of a piece as the key 0x3b: tmux would take it for the end of the command) and each key
  is a separate tmux call 150 ms apart; a send has at most 100 steps (texts and keys). A pane in copy mode is cancelled first. When a send submits text (text, then Enter) to a pane that runs an agent (Claude Code, seen on the screen), a dialog is refused (`dialog_open`),
  a busy agent is refused unless `--queue` (`busy_tab`), text starting with `/` or `!` is refused unless `--slash` (`slash_refused`; every submitted text is checked, and a send that submits more than one text to an agent needs `--queue`), and after the Enter the command checks that the text left
  the input box and presses Enter once more if it did not (`not_submitted` if it still did not). `--input` without a submission is never judged, so a dialog can be answered and a busy agent interrupted.

### The sysop

The `sysop` tool (`swarmbox tool install sysop`; user guide in [sysop.md](sysop.md), design in [plugins-design.md](plugins-design.md)) is a resident process that subscribes to the bus topic of `sysop.topic` (default `goal`) in the group `sysop.group` and, for each goal, runs
a **brain** (`claude -p` by default, any command that speaks MCP) with a few tools served by `swarmbox-sysop mcp`: `list_tabs`, `read_tab`, `run`, `input`, `wait`, `say`, `done`. The tools call `swarmbox-tabs` (`list`, `screen`, `send`) as a child process and never the bus,
so everything the sysop does is typed in a tmux tab you can see. The host side of the tool, not the brain, rates each `run` and `input` (low, medium, high or blocked, from the text and from what the tab runs) and routes it by the autonomy level:
a countdown the user can veto, an approval (the word `run` in the panel), or a refusal. Budgets (`sysop.max_steps`, `sysop.max_seconds`), the stop command and the audit file (`<state>/sysop/events.jsonl`, append-only, mode 0600) apply to every goal.
The panel opens beside the tab without taking the focus; veto, stop, approve and goal are tmux prefix keys (`Ctrl+A` then `V`, `X`, `a`, `g`; `S` shows or hides the panel). A key typed while a dialog of an agent is on the screen is always a high risk.
The tool is code of this repository (standard library Python, nothing downloaded); like `voice`, its `prepare.sh` refreshes its library at every box start and starts the subscriber. Its settings are the eight `sysop.*` keys of section 9,
passed to the box as `SWARMBOX_SYSOP_*` only when they differ from the default.

### The voice tool

The `voice` tool (`swarmbox tool install voice`; [voice.md](voice.md)) is an input and nothing more. It builds whisper.cpp inside the box, and `swarmbox-web` puts its front on the web terminal port: the microphone page and an audio entry with a fixed table of four routes under `/voice/`, next to ttyd.
Audio becomes text with Whisper and the text is published as `{"text": ...}` with source `voice` on the bus topic of `voice.topic` (default `goal`), through the socket of the bus. It has no planner, no panel and no code that reads or types into tmux. With nobody on the topic the page says so;
the sysop hears it when `sysop.topic` is the same name. Settings: `voice.language`, `voice.stt.model`, `voice.stt.vocabulary`, `voice.web` and `voice.topic` (section 9).

## 7. Web terminal and remote access

```
browser -> https://swarmbox.example.com -> Cloudflare Access (e-mail code) -> cloudflared (host) -> 127.0.0.1:7681 -> ttyd -> tmux (box)
```

**Inside the box.** ttyd (pinned, checksummed) runs tmux attached to `main`. It is on by default, listens only on `127.0.0.1:<WEB_PORT>` of the host
(always 7681 inside) and has no login of its own. The page is built at image build by `container/web/build-index.sh`, which joins ttyd's own page,
the clipboard bridge and the style into one file (ttyd serves a single file, measured). At start `swarmbox-web run` copies it to `box:/tmp/swarmbox/index.html` substituting
`padding`, `ctrlVPaste`, `ctrlCCopy` from `<workspace>/.config/swarmbox/web-terminal.conf`; every other key goes to ttyd as `-t key=value`.
`swarmbox-web restart` applies a change without ending the box. Details: [web-terminal.md](web-terminal.md).

**Remote access.** `swarmbox remote` is a wrapper that runs `cloudflare-setup.py` (the only part that needs `python3`, stdlib only, in the support folder) with
the box name and web port. `setup` asks for a domain, an e-mail and an API token (hidden input, never stored) and provisions the Access application with
the one-time-code login, a tunnel, the DNS record and the connector, a Podman container **on the host** named `<default name>-cloudflared`, image pinned in the
script (`DEFAULT_CONNECTOR_IMAGE`), restarted automatically. `status` reports it, `off` removes the record, route and application and stops the connector when no
other hostname uses the tunnel, `token` prints the tunnel token. The login length (`--session`) is kept on a rerun. `cloudflare.json` in the host config folder records domain,
hostname, box name and session. The tunnel token is read on the host only: from `SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN`, or from the config key `CLOUDFLARE_TUNNEL_TOKEN` only when
the file has mode 600 (checked as an octal number, not from `ls`); it never enters the box. `up` ends by making sure the connector runs; `reset` and `stop` never touch it.
Details and the end-to-end check list: [cloudflare.md](cloudflare.md).

## 8. Tools and shims

A tool is a directory `container/tools/<name>/` with `tool.conf` (manifest), `install.sh`, and optionally `shell.sh` (aliases for the interactive shell),
`prepare.sh` (run by `serve` at every start to render files into `box:/tmp/swarmbox`) and data files. Shipped: agents `claude`, `gemini`, `opencode`; tools `gcloud`
(with `gsutil`, `bq`), `clasp`, `go`, `poetry`, `voice` (an input: whisper.cpp, a multilingual Whisper model and a service that publishes what you say as a goal on the bus; `docs/voice.md`), `sysop` (the agent that operates the tabs from a goal; `docs/sysop.md`).

Manifest keys: `SCHEMA`, `NAME`, `KIND` (`tool` or `agent`), `PROVIDES` (commands), `VERSION`, `UPDATE` (`managed` or `self`), `UPDATE_CMD`, `YOLO_FLAGS`, `YOLO_ALIAS`,
`MCP_FLAGS`, `MCP_FORMAT`, `PORTS`, and `SHA256_<arch>` where the vendor's checksum is recorded.

**Shims.** A shim is a symlink named after a command, pointing to one dispatcher, `swarmbox-shim`. A call finds its tool in the index (`command tool`),
runs `swarmbox-tool run`, which, if the tool is not installed, takes an `flock` lock, prints `Installing <name> (first use)...`, runs `install.sh`, and then `exec`s the
real program. A failed install prints the reason and the next call retries. Two levels of manifests: the **user** level `<workspace>/.config/swarmbox/tools/<name>/`
(wins, no rebuild) and the **image** level `/usr/local/lib/swarmbox/tools/<name>/` (read-only). `swarmbox-tool link --system` runs at image build and writes the image shims, the
index and `tool-ports`; `link --user` runs at start and at every entry. `PATH` order: user shims, image shims, `<workspace>/.local/share/swarmbox/tools/*/current/bin`, so once installed the
real binary wins. There are no project-level tools: a repository's `install.sh` would run with network and your keys.

**Installed layout:** `<workspace>/.local/share/swarmbox/tools/<name>/<version>/` with a `current` link (managed) or `self/` (self-updating). Installers write only inside their prefix.
Each install records `NODE_MAJOR`, `ARCH` and `LIBC` in `.swarmbox-env`; a different `ARCH` makes the shim refuse (exit 69) and ask for a reinstall, a different Node or libc warns.
`swarmbox-tool doctor [--fix]` lists `ok`, `needs reinstall` or `missing`.

**Updating.** Managed tools are pinned in the manifest except agents, which say `latest`. `update NAME` installs the new version side by side and moves `current`; `use NAME VERSION` rolls
back. A once-a-day, online-only notice says when a newer version exists (`SWARMBOX_UPDATE_CHECK=0` turns it off). Claude Code is `UPDATE=self`: installed once by the vendor's native
installer (npm under a prefix cannot update itself, measured), then it updates itself; `update` runs `claude update`. This costs reproducibility and runs new vendor code in the box.
gcloud's checksum is recorded by `dev/record-checksums.sh`. `WITH_TOOLS` is a build argument of the Dockerfile that bakes tools into the image with the same installer.

**Agents.** For every installed or declared agent the interactive shell gets an alias from the manifest, for example `claude --dangerously-skip-permissions --mcp-config ...`, so agents are
auto-approve by default; `command claude` bypasses it, `SWARMBOX_YOLO=0` turns the aliases off. `yolo` runs the default agent (`AGENT`, else the first agent of `WITH`, else the first
agent manifest by name). OpenCode gets no alias (`YOLO_ALIAS=0`): its `--auto` flag is not accepted before a subcommand, so only `yolo` uses it. OpenCode's local-LLM setup is
`prepare.sh` rendering `box:/tmp/swarmbox/opencode.json` from `LOCAL_LLM_*` variables.

**MCP.** `container/mcp/<name>/config.json` describes an MCP server (`command`, `args`, `env`, `browserUrlArgs`). `swarmbox-mcp generate` writes `<workspace>/.claude/mcp-servers.json`;
a user file `<workspace>/.config/swarmbox/mcp/<name>/config.json` can override or set `{"enabled": false}`. The only shipped server is `chrome-devtools-mcp`, pinned and installed in the
image (never `npx`), with Chromium. When `BROWSER_URL` is set it attaches to a remote Chrome instead. OpenCode gets a mirrored copy (`MCP_FORMAT=opencode`).

Adding a tool: `swarmbox tool new NAME` (a `tool.conf` and `install.sh` skeleton; `--repo` or `--dir`), then `swarmbox tool validate`. [../CONTRIBUTING.md](../CONTRIBUTING.md) lists how pins are bumped.

## 9. Configuration

One file for creation settings: `host:~/.config/swarmbox/config` (second box: `host:~/.config/swarmbox/<name>/config`). One `KEY=VALUE` per line, the value literal (no quoting, expansion
or newline); `#` lines and blank lines ignored; an empty value means the default; lists are comma separated; unknown keys are ignored with one warning (and refused by `config set`).
Precedence: environment `SWARMBOX_<KEY>`, then the file, then the default. The file is never sourced, only read line by line. `NAME` is not a key: it selects the folder, so it comes from
`SWARMBOX_NAME` only (letters, digits, `.`, `_`, `-`; not `config`). Defaults of the box name and the image repository live only in `container/host/DEFAULTS` (D40).

| Key | Default | Meaning |
|---|---|---|
| `WORKSPACE` | `~/swarmbox` | the folder mounted as the home |
| `HOSTNAME` | the box name | container hostname |
| `TZ` | `local` | `local`, `off` or `Area/City` |
| `INIT` | `auto` | `--init` (zombie reaping); `auto` tests support |
| `PORTS` | empty | extra published ports, `127.0.0.1` unless an address is given (a warning for `0.0.0.0`); the tools' `PORTS` are added |
| `HOST_ACCESS` | `0` | adds `host.containers.internal:host-gateway` |
| `BROWSER_URL` | empty | remote Chrome for chrome-devtools; a bare number or `HOST:PORT` |
| `WEB`, `WEB_PORT` | `1`, `7681` | the web terminal and its host port (on `127.0.0.1`) |
| `WITH` | empty | tools to install at start |
| `AGENT`, `YOLO` | first agent of `WITH`, `1` | the agent `yolo` starts; `0` disables the auto-approve aliases |
| `ENV_KEYS` | empty | names of host variables passed at creation (section 10) |
| `IMAGE` | `<repo>:<version>` | image reference (letters, digits, `. _ / : @ -`, never starting with `-`); written by `update` |
| `CLOUDFLARE_TUNNEL_TOKEN` | unset | optional, mode 600 only, host only |
| `voice.language` | `auto` | Whisper language of the `voice` tool: `auto` or a code such as `pt` (no `pt-br`); passed as `SWARMBOX_VOICE_LANGUAGE` |
| `voice.stt.model` | `small` | multilingual Whisper model (`tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`), never `.en`; `SWARMBOX_VOICE_STT_MODEL` |
| `voice.stt.vocabulary` | empty | words given to Whisper as its initial prompt (at most 500 characters); `SWARMBOX_VOICE_STT_VOCABULARY` |
| `voice.web` | `1` | `0` keeps the voice front off: the web terminal port then goes straight to ttyd, with no voice button; `SWARMBOX_VOICE_WEB` |
| `voice.topic` | `goal` | the bus topic the voice tool publishes its goals to (a topic name: `[a-z0-9][a-z0-9._-]{0,62}`); passed as `SWARMBOX_VOICE_TOPIC` |
| `sysop.brain` | `claude` | the brain of the `sysop` tool: a preset name or a command template (no line break; [sysop.md](sysop.md)); `SWARMBOX_SYSOP_BRAIN` |
| `sysop.model` | `haiku` | the model the `claude` preset asks for; `SWARMBOX_SYSOP_MODEL` |
| `sysop.autonomy` | `confirm-risky` | `confirm-all`, `confirm-risky` or `auto`; `SWARMBOX_SYSOP_AUTONOMY` |
| `sysop.countdown` | `4` | seconds an action waits for a veto, 0 to 30; `SWARMBOX_SYSOP_COUNTDOWN` |
| `sysop.max_steps` | `20` | tool calls of one goal, 1 to 100; `SWARMBOX_SYSOP_MAX_STEPS` |
| `sysop.max_seconds` | `300` | seconds of one goal, 10 to 3600; `SWARMBOX_SYSOP_MAX_SECONDS` |
| `sysop.topic` | `goal` | the bus topic the sysop listens on (same charset as `voice.topic`; both default to `goal`, which is the only link between the two tools); `SWARMBOX_SYSOP_TOPIC` |
| `sysop.group` | `sysop` | the group the sysop subscribes with, so several sysops share the goals; `SWARMBOX_SYSOP_GROUP` |

The `voice.*` and `sysop.*` keys are lower case with dots (`sysop.max_steps` keeps its underscore); the environment variable of a key is `SWARMBOX_` plus the key in upper case with `.` turned into `_`. They are creation settings like the others (applied by `swarmbox reset`), but
they are passed to the box, and enter the fingerprint, only when they differ from the default.

Also environment only: `SWARMBOX_WEB_DOMAIN`, `SWARMBOX_WEB_HOSTNAME` (public address printed by `url`), `SWARMBOX_CLOUDFLARED_IMAGE`; in the box `SWARMBOX_STARSHIP=0` (plain prompt),
`SWARMBOX_UPDATE_CHECK=0`. `config set` writes under `umask 077`, replaces the file by `mv`, and refuses to write if `chmod 600` fails. `config list` shows each key with its source
and the token only as `set` or `unset`.

Always applied, not configurable: `--userns=keep-id:uid=1000,gid=1000`, `--pids-limit=16384`, `--tmpfs /tmp/swarmbox`, the nested-Podman options (section 11), the web port mapping
`127.0.0.1:<WEB_PORT>:7681`, `-e TERM -e COLORTERM` on every entry, and `-e SWARMBOX_NAME`, `SWARMBOX_WEB`, `SWARMBOX_YOLO`, `SWARMBOX_WITH`, `SWARMBOX_AGENT`, `SWARMBOX_BROWSER_URL`
when set. There is no host-network mode.

## 10. Environment variables

Keys the agents need (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, ...) are passed **only when the box is created**. Their names are in `ENV_KEYS` (`swarmbox env add NAME`); at creation the script emits
`-e NAME` without a value, so Podman reads it from the terminal that runs `swarmbox` and the value is not on any command line. A name listed but unset in that terminal produces a warning. The
label `swarmbox.env-hash` holds a hash of `NAME=value` (or `NAME` when unset), so a later entry can say "the variables changed on the host; run `swarmbox reset`". Names starting with
`SWARMBOX_CLOUDFLARE_` are refused. `LOCAL_LLM_URL`, `_MODEL`, `_KEY`, `_CONTEXT`, `_OUTPUT` are ordinary entries (OpenCode reads them).

SwarmBox stores no values: keeping the variables exported is your business (shell file, password manager, direnv), and `reset` re-reads them. The values are in the container's configuration
(`podman inspect`) and in the environment of every process in the box, so the agent can read them: scoped tokens are the protection, not the sandbox. Every process sees every listed name.
A credential proxy on the host would be the only way to keep a key from the agent; it is not built. Claude Code's own login lives in `<workspace>/.claude` and survives a reset.

## 11. Nested Podman and its isolation cost

Agents get a full rootless Podman **inside** the box with no path to your Podman (its socket is never mounted). It is always on. Details and use: [nested-podman.md](nested-podman.md).

Created with the box: `--device /dev/net/tun`, `--security-opt unmask=/proc/*`, the volume `<name>-containers` at `<workspace>/.local/share/containers` (its files are owned by sub-IDs your user could not delete), and,
on Linux and WSL, the host connection. `swarmbox up` stops (exit 3) when the host has no `/dev/net/tun`; `serve` checks again.

Image settings that make it work: packages `podman`, `netavark`, `aardvark-dns` (DNS between nested containers), `iptables`, `uidmap`, `libcap2-bin`; file capabilities (`setcap cap_setuid`, `cap_setgid`) on `newuidmap` and
`newgidmap` instead of the setuid bit (setuid-root binaries do not work in an unprivileged container); `/etc/subuid` and `/etc/subgid` `agent:1001:64535`; `storage.conf` with native `overlay` and
`ignore_chown_errors` (about 64 thousand user IDs, so an image whose files are owned by 65534 or 65532 must run `--user root`, which inside the box is your own user); `containers.conf` with
`utsns = "host"` (the nested `crun` cannot call `sethostname`; nested containers share the box's hostname), `cgroup_manager = "cgroupfs"`, `events_logger = "file"` (no systemd inside) and
`network_backend = "netavark"`. Neither file lives under the home, because the home is a bind mount.

**The cost.** `/dev/net/tun` and an unmasked `/proc` make the box less isolated than a plain container; this is deliberate and always on. Two limits found on the development box: a third nesting level
(a SwarmBox inside a SwarmBox) cannot run nested Podman; and a host whose user namespace is narrower than the box's subuid range makes `newuidmap` fail (works with a normal 65536 range, not run on a real host).

## 12. Security model

SwarmBox reduces the damage of a mistake. It is not a virtual machine and does not make untrusted code safe to run. A container shares the kernel with your machine; its isolation comes from user
namespaces, cgroups and a seccomp profile, not from a hypervisor. A kernel or runtime vulnerability, or a misconfiguration, can let code in the box escape. For untrusted work use a virtual machine or
a dedicated machine; what is known about stronger isolation is in [microvm.md](microvm.md).

**Protected:** your files and processes outside the workspace folder, and your Podman socket. The box is a rootless Podman container (root inside is an unprivileged user of your machine); the web terminal
listens only on `127.0.0.1` and has no login on its own port; the Cloudflare credentials and connector stay on the host; no ports beyond `127.0.0.1` unless you ask; no host-network mode.

**Not protected (assume all of it):**
- The agent can change or delete everything in the workspace (projects, logins, the SSH key), uses `sudo`, and has open outbound network.
- Passed variables are visible to every process in the box and to `podman inspect` on the host.
- The box is persistent: an agent keeps running, with its keys, while you are away.
- The SSH key is in the workspace: anything in the box can use it. Use a deploy key per repository.
- With remote access on, whoever passes the Cloudflare login has the agent's control: a shell with `sudo`. The `--session` length is the time a stolen or forgotten session stays usable; an administrator can revoke
  sessions in the Zero Trust dashboard (read from Cloudflare's documentation, not tried).
- Tools are downloaded on the agent's request, pinned and checksummed where the vendor publishes one; agents install `latest`, and Claude Code updates itself.
- The script runs on the host with your privileges and is accepted as coming from the signed image you already trust (D26); the review is [security-review.md](security-review.md), written by the same AI that built it,
  with no human or third-party review yet. The tunnel token may be in the host config, mode 600, and never enters the box.

**No telemetry.** SwarmBox makes no network call of its own except to pull the image, to install a tool you asked for, to check for a tool update, and, with `remote`, to reach Cloudflare. Logs stay local:
`<workspace>/.local/state/swarmbox/` and, on the host, `~/.local/state/swarmbox/` (locks, `notices`). Third-party software in the image is listed in `THIRD_PARTY_NOTICES.md`.

## 13. Image and updates

The image is the root `Dockerfile` (about 1.75 GB built; no agent inside): `node:24-trixie-slim` (Debian 13), user `agent` UID/GID 1000 (the base user renamed, passwordless `sudo` on purpose), git, curl, python3 and venv,
build tools, jq, tmux, vim, openssh-client and similar, Podman and its network packages, Chromium, `chrome-devtools-mcp` (pinned), `uv`, ttyd and Starship (pinned, checksummed), a Python venv at `/opt/flow`,
`container/` scripts and configuration (including `swarmbox-bus` and `swarmbox-tabs`, one Python file each), `cloudflare-setup.py`, and the tool manifests with their shims. The `voice` and `sysop` tools are in the image as source, and nothing of them is installed or running until you install them. `ENTRYPOINT swarmbox-entrypoint`, `CMD serve`. Subcommands of the entrypoint: `serve`, `attach`, `install`,
`pubkey`, `tool`, `bus`, `tabs`, `host-helper` (the archive of the script and support files on stdout), anything else is run as given. Layers: stable first, volatile last; every `RUN` that downloads cleans up in the same `RUN`; `NPM_CONFIG_CACHE` is
`/opt/npm-cache`, owned by `agent`. Every version is an `ARG` with a default; `CONTRIBUTING.md` says how they are bumped. A tool the image needs that is not in Debian is fetched with its published checksum verified. **tmux is the one exception to "the Debian package"**: Debian 13 has 3.5a, which has no pane scrollbar (tmux 3.6 added it), so the image installs one exact backport, `TMUX_VERSION` (3.7c-1~bpo13+1), pinned by SHA-256 for amd64 and arm64 and fetched from the archive or, when backports has moved on, from `snapshot.debian.org` by SHA-1; each source is checked against the SHA-256 before the file is installed. `container/config/tmux.conf` enables `pane-scrollbars on` with `set -gq`, so the same file loads on the older tmux of a development machine, which ignores it. `on` and not `modal`: with `modal` the pane is resized (one column) each time copy mode starts and ends, and the program in it gets a resize and redraws while you read its output [verified: tmux 3.7c with a program that logs SIGWINCH: 80 -> 79 -> 80 with `modal`, 79 throughout with `on`]; a program on the alternate screen gets the whole width and no bar, and one that asks for the mouse gets the wheel and tmux does not enter copy mode [verified: same tmux, a program that enables mouse tracking received the three wheel events].

**Distribution.** Image `ghcr.io/feroult/swarmbox`, multi-arch (amd64, arm64), tags `X.Y.Z`, `X.Y` and `latest`, published with each release. `.github/workflows/release.yml` runs the tests, a native build per architecture, a check that the
script in the image reports the tag's version, a vulnerability scan (grype), the manifest list, keyless signing (cosign), and the SBOM (syft). To build it yourself, see CONTRIBUTING.md (`dev/dev-build.sh` inside a development box). A missing image is pulled by `up`, never built.

**`swarmbox update`.** Without options it pulls the moving `X.Y` tag of the series in `IMAGE` (`--to TAG` takes exactly that tag). It extracts the archive of the pulled image into a temporary folder (the
archive's member names are checked: no absolute or `..` names, only files and folders), reads the exact `X.Y.Z` from it, creates a local tag `<repo>:X.Y.Z`, renames the folder over the old support files,
replaces the script itself (a copy next to it, then a rename, so a running copy is never cut) when the image's is newer, and keeps it with a message when it is newer than the image or its folder cannot be written,
writes `IMAGE=<repo>:X.Y.Z`, and prints `updated to X.Y.Z; run swarmbox reset to use it`. Any failure before the rename changes nothing. It never recreates the box. The exact local tag makes a later
`reset` work offline. Rollback: `swarmbox update --to <older tag>` refreshes the support files and keeps the newer script (it still runs), or install the older tag again with its `install`. The workspace is kept either way.
An `IMAGE` with no `X.Y` series (a digest, `latest`, `dev`) needs `--to`.

## 14. Repository layout

```
Dockerfile                  the image
container/entrypoint.sh     serve, attach, install, pubkey, tool, bus, tabs, host-helper
container/scripts/          dirs, banner, messages, ssh-key, starship-init, swarmbox-{attach,bus,tabs,install,mcp,shim,tool,web}
container/host/             swarmbox-host (the `swarmbox` script), VERSION, DEFAULTS   (the archive of `host-helper`)
install.sh                  the release installer (downloads swarmbox, checks its sha256)
container/config/           tmux.conf, tmux-browser-keys.conf, starship.toml, bashrc.sh (the shell fragment), ssh-swarmbox.conf
container/tools/<name>/     tool manifests and installers;  container/mcp/<name>/  MCP server descriptions
container/web/              ttyd page parts and build-index.sh
cloudflare-setup.py         the back end of `swarmbox remote`
dev/                        dev-build, name-check, release-check, release-version, record-checksums, gen-notices, kata-probe
tests/                      unittest scripts (stdlib only); run `sh tests/run_all.sh`
docs/                       this file, security-review, release-checklist, microvm, web-terminal, cloudflare, nested-podman, uninstall, history/
.github/workflows/          ci.yml, release.yml
```

## 15. Decisions

Decisions that are still true. The full reasoning of D1 to D40 is in [history/decision-log.md](history/decision-log.md).

| Id | Decision | Reason |
|---|---|---|
| D1 | One persistent box; every tab and the browser share tmux session `main` | one environment, nothing to reconcile |
| D2 | Neutral image, tools and agents installed on demand through shims | small image, independent versions |
| D3 | Claude Code updates itself (`UPDATE=self`) | npm install cannot self-update; vendor path works |
| D4 | OpenCode is a shim like Claude Code; local-LLM setup lives in its tool directory | no special case in the core |
| D5 | Nested Podman is always on, not a setting | agents need containers; the cost is stated in section 11 |
| D6 | macOS through a Podman machine | wide audience; not yet tested |
| D7 | No host-network mode | keeps the network surface small |
| D10 | XDG layout in the workspace; regenerated files in `box:/tmp/swarmbox` | one rule per file |
| D11 | Workspace chosen in the host config (`swarmbox config set WORKSPACE DIR`), default `~/swarmbox` | where you run `swarmbox` does not matter |
| D12 | Variables are passed only at creation; names in config, values from the host environment | no value on disk or on a command line |
| D13 | The ttyd page is built into the image | versioned, tested, signed |
| D14 | Cloudflare credentials and connector stay on the host | the agent never sees the tunnel |
| D15 | One script on the `PATH`, not a shell function or an alias | works from any shell and from scripts; no startup file to edit |
| D16 | The script is POSIX `sh`; only `remote` is Python | runs on a bare host |
| D17 | `update` records `IMAGE` in the host config; no startup file is edited | rollback and reset stay simple |
| D18 | No project-level tools | an `install.sh` from a clone would run with your keys |
| D19 | No throwaway-container mode; a second box uses `SWARMBOX_NAME` | one concept of "box" |
| D20 | `install` only prints an installer; the installer writes one file, the support files and the config keys that are unset | nothing is written until you run it with `sh`; no startup file |
| D21 | Agents install `latest`; every other tool is pinned | agents change fast; the rest must be reproducible |
| D23 | `chrome-devtools-mcp` pinned in the image, run directly, never `npx` | no download when the browser starts |
| D25 | Apache-2.0 license; the name SwarmBox must be checked before the first release | see release checklist |
| D26 | The script is trusted as part of the signed image; `install.sh` only compares a checksum from the same release | no separate signature unless asked |
| D27 | `update` only pulls and tells you to `reset` | recreating ends sessions |
| D28 | No file of variable values; the tunnel token may be in the host config only with mode 600 | the one unavoidable secret, guarded |
| D30 | A fingerprint mismatch only warns | `reset` ends sessions |
| D31 | A second box's config is `~/.config/swarmbox/<name>/config` | the name selects the folder |
| D33 | `update` replaces the script only by a newer one; the support files of another version give one warning, once | `update` must not be undone by the next call |
| D34 | WSL2 only with the workspace on the Linux filesystem | permissions on `/mnt/<letter>` break `keep-id` |
| D35 | `update` writes the exact `X.Y.Z` tag and tags it locally | `reset` works offline |
| D36 | No `swarmbox uninstall`; manual steps documented (delete the script and the config) | no rc file was edited, so there is none to undo |
| D39 | Cloudflare remote access is in 2.0 | needed from a phone or another computer |
| D40 | Default names (box, image repository) live only in `container/host/DEFAULTS`; both are `swarmbox` | one file to flip for release |

## 16. Not done, and open questions

- Nothing has run on a real host: macOS, a real WSL with a Windows drive, a host UID other than 1000, Podman older than 4.3 (the 4.3 limit is where `keep-id:uid=,gid=` was observed; the true minimum is unknown),
  `python3` on a clean macOS, bash 3.2 and BSD `stat` for the script.
- `ci.yml` and `release.yml` ran on GitHub for 2.0.0-beta.1 and 2.0.0-beta.2 (both architectures, grype, cosign keyless signing, SBOM). Nobody has yet verified the published image on a clean machine from the README alone.
- Cloudflare was only tested against a fake API; the real end-to-end check is in [cloudflare.md](cloudflare.md). Whether the connector restarts after a reboot needs `podman-restart.service` enabled for the user (not tried).
- Nested Podman has not been started on a real host with a normal subuid range; the third nesting level cannot run it.
- The OpenCode package: `@opencode/cli` 2.x or `opencode-ai` 1.x; the installer has one variable `PACKAGE` (decision pending).
- A human review of the host script and the security review; the licence checks of `THIRD_PARTY_NOTICES.md`.
- Stronger isolation (a microVM runtime): untested, see [microvm.md](microvm.md). A credential proxy on the host, a separately signed script asset and restart of the box after a reboot are not built.
- After `remote setup` for a second box, `cloudflare.json` keeps one name, so the first box prints no public address until its setup is run again.
- `swarmbox <command>` prints tmux's own `[exited]` line before the command's output; accepted.
- Code comments still cite section numbers of an earlier version of this file; the names of the functions and files they cite are right.
